"""Predictions on the samples of a user, planned with the semantic discovery.

The prediction page offers every sample of the user. For a sample, the discovery tells which
models are ready, which need preparation steps first (and which ones) and which cannot run. A
prediction adds to the plan of the sample the preparation steps the selected models need, shared
between models, and one prediction node per model after the node that gives it its input.
"""
import logging

from django.contrib.humanize.templatetags.humanize import naturaltime
from rdflib import URIRef

from core.models import File, ProcessGroup, TaskOutput, TaskStatus
from core.orchestration import PlanError, extend_plan
from core.steps import UnknownStepError, get_step, software_label
from semantics.discovery import Status, discover
from semantics.provenance import task_iri
from semantics.registry.descriptors import model_iri
from semantics.registry.graph import registry_graph
from semantics.sample import sample_graph
from semantics.trust import RulesError, antibiotic_iri, assess, evidence, load_rules

from .adapters.registry import get_model_supported_antibiotics, get_model_version
from .models import NO_RESULT, PredictionRun, PredictionTask
from .steps import PREDICTION_STEP_PREFIX

logger = logging.getLogger(__name__)

ACTIVE = (TaskStatus.PENDING, TaskStatus.RUNNING)


# --- Samples and what can run on them

def get_sample_options(user):
    """Every sample (process) of the user, newest first. Samples with tasks in progress cannot be used yet."""
    options = []
    for process in ProcessGroup.objects.filter(user=user).prefetch_related('tasks').order_by('-id'):
        tasks = list(process.tasks.all())
        last_update = max((task.updated_at for task in tasks), default=None)
        options.append({
            'id': str(process.id),
            'label': f'{process.name} · {naturaltime(last_update)}' if last_update else process.name,
            'processing': is_processing(process),
        })
    return options


def is_processing(process):
    return process.tasks.filter(status__in=ACTIVE).exists()


def get_user_sample(user, process_id):
    if not process_id:
        raise ValueError('Select a sample.')
    try:
        return ProcessGroup.objects.get(pk=int(process_id), user=user)
    except (ValueError, ProcessGroup.DoesNotExist):
        raise ValueError('Selected sample not found.')


def get_compatibility(process):
    """What the discovery says about every model for this sample (see semantics.discovery)."""
    # The discovery only compares the data of the sample: its IRI does not need to be its page.
    return discover(registry_graph(), sample_graph(process, f'urn:cocos:process:{process.pk}'))


def describe_compatibility(process):
    """The compatibility of every model with the sample, for the prediction page."""
    return [
        {
            'model': result.model,
            'version': get_model_version(result.model),
            'status': result.status.value,
            'steps': [describe_step(get_step(step.step)) for step in result.steps],
            'reasons': list(result.reasons),
        }
        for result in get_compatibility(process)
    ]


def describe_step(step):
    """A preparation step for the prediction page: its label, the tools it would use (e.g. 'Bakta
    1.12.1') and all its software with the databases; `tools` and `software` are None if unknown."""
    entries = step.expected_software()
    if entries is None:
        return {'label': step.label, 'tools': None, 'software': None}
    return {
        'label': step.label,
        'tools': [software_label(entry) for entry in entries if entry.get('type') == 'tool'],
        'software': [software_label(entry) for entry in entries],
    }


# --- How much the predictions can be trusted

def prediction_trust(process, runs):
    """{run id: {model: {antibiotic: trust}}} of the results of the prediction `runs` of `process`
    (see semantics.trust); empty if the trust rules have mistakes."""
    sample = URIRef(f'urn:cocos:process:{process.pk}')
    graph = sample_graph(process, str(sample), with_provenance=True)
    trust = {}
    for task, model_name, antibiotic, _, result in assess_predictions(process, graph, sample, runs):
        trust.setdefault(task.run_id, {}).setdefault(model_name, {})[antibiotic] = result
    return trust


def assess_predictions(process, graph, sample, runs=None):
    """(task, model name, antibiotic, its ARO term or None, trust) for each result of the completed
    predictions of `process` (of `runs`, if given). `graph` is the RDF of the process with its
    provenance, whose IRI is `sample`. Nothing if the trust rules have mistakes."""
    try:
        rules = load_rules()
    except RulesError:
        logger.exception('The trust rules have mistakes; predictions are shown without their trust')
        return []
    registry = registry_graph()
    tasks = PredictionTask.objects.filter(process=process, status=TaskStatus.COMPLETED).order_by('id')
    if runs is not None:
        tasks = tasks.filter(run__in=runs)
    assessed = []
    for task in tasks:
        try:
            model_name = task.get_step().model_name
        except UnknownStepError:
            continue  # a model that is no longer registered
        model = model_iri(model_name)
        for antibiotic, value in task.results.items():
            if value == NO_RESULT:
                continue
            term = antibiotic_iri(registry, model, antibiotic)
            facts = evidence(registry, graph, sample, task_iri(sample, task), model, term)
            assessed.append((task, model_name, antibiotic, term, assess(registry, facts, antibiotic, rules)))
    return assessed


# --- Starting a prediction

def get_valid_prediction_antibiotics(model_names, antibiotics):
    return [antibiotic for antibiotic in antibiotics if
            any(antibiotic in get_model_supported_antibiotics(model_name) for model_name in model_names)]


def start_prediction(user, model_names, antibiotics, process_id):
    if not model_names:
        raise ValueError('Select at least one model.')
    if not antibiotics:
        raise ValueError('Select at least one antibiotic.')

    process = get_user_sample(user, process_id)
    if is_processing(process):
        raise ValueError('This sample is still being processed. Wait until it finishes.')

    valid_antibiotics = get_valid_prediction_antibiotics(model_names, antibiotics)
    if not valid_antibiotics:
        raise ValueError('No valid antibiotic/model combinations found.')

    compatibility = {result.model: result for result in get_compatibility(process)}
    for model_name in model_names:
        result = compatibility.get(model_name)
        if result is None or result.status == Status.INCOMPATIBLE:
            reasons = ' '.join(result.reasons) if result else 'Unknown model.'
            raise ValueError(f'The model {model_name} cannot run on this sample. {reasons}')

    run = PredictionRun.objects.create(process=process, selected_models=model_names,
                                       selected_antibiotics=valid_antibiotics)
    try:
        nodes, inputs = _plan(process, run, [compatibility[name] for name in model_names], valid_antibiotics)
        extend_plan(process, nodes, inputs)
    except PlanError:
        run.delete()
        raise ValueError('These models cannot be planned together on this sample.')

    run.refresh_from_db()
    return run


def _plan(process, run, results, antibiotics):
    """(plan nodes, {node id: {role: uploaded File}}) for the preparation steps and predictions of
    `results`, the compatibility of each selected model.

    For each model: one node per preparation step (a step already planned with the same inputs is
    reused, so models that need the same preparation share it), then its prediction.
    """
    produced_by = _produced_by(process)
    nodes, inputs, shared = [], {}, {}
    for result in results:
        path_nodes = []  # the node of each preparation step of this model, in order
        for planned in result.steps:
            after, uploaded = _resolve(planned.inputs, path_nodes, produced_by)
            key = (planned.step, tuple(after), tuple(sorted((role, file.pk) for role, file in uploaded.items())))
            if key not in shared:
                shared[key] = f'run{run.pk}_step{len(nodes) + 1}'
                _add_node(nodes, inputs, shared[key], planned.step, after, uploaded)
            path_nodes.append(shared[key])

        model_antibiotics = [a for a in antibiotics if a in get_model_supported_antibiotics(result.model)]
        if not model_antibiotics:
            continue  # the column of the model shows no result
        after, uploaded = _resolve(result.inputs, path_nodes, produced_by)
        _add_node(nodes, inputs, f'run{run.pk}_{result.model}', f'{PREDICTION_STEP_PREFIX}{result.model}',
                  after, uploaded, run=run.pk, parameters={'antibiotics': model_antibiotics})
    return nodes, inputs


def _produced_by(process):
    """{(file id, role): node} for the outputs of the completed nodes of a process. A file can be
    several outputs: a Bakta JSON is the annotation of one node and the genes of another."""
    outputs = TaskOutput.objects.filter(task__process=process, task__status=TaskStatus.COMPLETED)
    return {(file_id, role): node for file_id, role, node in outputs.values_list('file_id', 'role', 'task__plan_node')}


def _resolve(sources, path_nodes, produced_by):
    """(nodes to run after, {role: uploaded File}) for the inputs ((role, Source), ...) of a node.

    An input comes from an earlier preparation step, from the completed node that produced a file
    of the sample, or, for a file the user uploaded, as an uploaded input.
    """
    after, uploaded = [], {}
    for role, source in sources:
        if source.step is not None:
            after.append(path_nodes[source.step])
        elif (int(source.file), source.role) in produced_by:
            after.append(produced_by[(int(source.file), source.role)])
        else:
            uploaded[role] = File.objects.get(pk=int(source.file))
    if after and uploaded:
        raise PlanError('A node cannot take both uploaded files and outputs of other nodes')
    return sorted(set(after)), uploaded


def _add_node(nodes, inputs, node_id, step, after, uploaded, **extra):
    nodes.append({'id': node_id, 'step': step, 'after': after, **extra})
    if uploaded:
        inputs[node_id] = uploaded
