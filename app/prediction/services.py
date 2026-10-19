"""Predictions on the samples of a user, planned with the semantic discovery.

The prediction page offers every sample of the user. For a sample, the discovery tells which
models are ready, which need preparation steps first (and which ones) and which cannot run. A
prediction adds to the plan of the sample the preparation steps the selected models need, shared
between models, and one prediction node per model after the node that gives it its input.
"""
from django.contrib.humanize.templatetags.humanize import naturaltime

from core.models import File, ProcessGroup, TaskOutput, TaskStatus
from core.orchestration import PlanError, extend_plan
from core.steps import get_step
from semantics.discovery import Status, discover
from semantics.registry.graph import registry_graph
from semantics.sample import sample_graph

from .adapters.registry import get_model_supported_antibiotics
from .models import PredictionRun
from .steps import PREDICTION_STEP_PREFIX

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
            'status': result.status.value,
            'steps': [get_step(step.step).label for step in result.steps],
            'reasons': list(result.reasons),
        }
        for result in get_compatibility(process)
    ]


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
    """Plan nodes (and uploaded inputs) for the preparation steps and predictions of `results`.

    A preparation step needed by several models is planned once. Each input comes either from a
    node of this plan, from the completed node that produced a file of the sample, or, for a file
    the user uploaded, as an uploaded input.
    """
    # {(file id, role): node} for the outputs of completed nodes; a file can be several outputs
    # (a Bakta JSON is the annotation of one node and the genes of another).
    produced_by = {(file_id, role): node for file_id, role, node in
                   TaskOutput.objects.filter(task__process=process, task__status=TaskStatus.COMPLETED)
                   .values_list('file_id', 'role', 'task__plan_node')}
    nodes, inputs, shared = [], {}, {}

    def add(step, sources, path_nodes, extra=None):
        after, uploaded = _resolve(sources, path_nodes, produced_by)
        key = (step, tuple(sorted(after)), tuple(sorted((role, file.pk) for role, file in uploaded.items())))
        if extra is None and key in shared:
            return shared[key]
        node_id = extra.pop('id') if extra else f'run{run.pk}_step{len(nodes) + 1}'
        nodes.append({'id': node_id, 'step': step, 'after': after, **(extra or {})})
        if uploaded:
            inputs[node_id] = uploaded
        if extra is None:
            shared[key] = node_id
        return node_id

    for result in results:
        path_nodes = []  # the node of each step of this model's preparation, in order
        for planned in result.steps:
            path_nodes.append(add(planned.step, planned.inputs, path_nodes))
        model_antibiotics = [a for a in antibiotics if a in get_model_supported_antibiotics(result.model)]
        if not model_antibiotics:
            continue  # its column shows no result
        add(f'{PREDICTION_STEP_PREFIX}{result.model}', result.inputs, path_nodes, extra={
            'id': f'run{run.pk}_{result.model}',
            'run': run.pk,
            'parameters': {'antibiotics': model_antibiotics},
        })
    return nodes, inputs


def _resolve(sources, path_nodes, produced_by):
    """(nodes it runs after, {role: uploaded File}) for the inputs ((role, Source), ...) of a node."""
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
