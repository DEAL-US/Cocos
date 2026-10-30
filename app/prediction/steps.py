"""Prediction steps: one step per registered prediction model, resolved from the model registry.

A model with an adapter runs in Cocos (ModelPredictionStep); a model whose descriptor says it runs
in a service is sent there as a job (RemoteModelPredictionStep). Both store the same results.
"""
import csv
import io
import logging
import os
from functools import lru_cache
from pathlib import Path

from rdflib.namespace import RDFS

from core.models import File
from core.utils import sha256_of
from core.steps import Busy, ExternalStep, LocalStep, Started, Step, StepError, register_step_provider
from semantics.namespaces import OBO
from semantics.registry.terms import terms_graph

from . import remote
from .adapters.registry import (
    get_model_adapter_class,
    get_model_endpoint,
    get_model_ports,
    get_model_supported_antibiotics,
    get_model_supported_organisms,
    get_model_version,
    get_model_weights,
    list_registered_models,
)
from .models import NO_RESULT, PredictionTask
from .results import CALLS, as_result
from .runs import finish_run_if_done, mark_run_started

logger = logging.getLogger(__name__)

PREDICTION_STEP_PREFIX = 'predict_'


def get_prediction(model_name: str, antibiotic: str, file):
    """What the adapter of the model predicts: a probability, or a result (see prediction.results)."""
    model_cls = get_model_adapter_class(model_name)
    if not model_cls:
        raise ValueError(f'Model {model_name} not found in registry.')

    adapter = model_cls(antibiotic=antibiotic)

    adapter.load()
    return adapter.predict(file)


@lru_cache(maxsize=256)
def _weights_sha256(path, modified):
    """SHA-256 of a weights file; cached by path and modification time, as weights rarely change."""
    return sha256_of(path)


class BaseModelStep(Step):
    """Predict antibiotic resistance with one registered model; its ports come from the model descriptor."""
    category = 'prediction'
    task_model = PredictionTask
    default_parameters = {'antibiotics': []}

    def __init__(self, model_name):
        self.model_name = model_name
        self.key = f'{PREDICTION_STEP_PREFIX}{model_name}'
        self.label = model_name
        self.consumes, self.produces = get_model_ports(model_name)

    @property
    def supported_antibiotics(self):
        return get_model_supported_antibiotics(self.model_name)

    @property
    def supported_organisms(self):
        return get_model_supported_organisms(self.model_name)

    def on_task_started(self, task):
        if task.run_id:
            mark_run_started(task.run_id)

    def on_task_finished(self, task):
        if task.run_id:
            finish_run_if_done(task.run_id, task)

    # A prediction whose preparation failed will never get its input.
    cancel_when_blocked = True

    def on_node_cancelled(self, process, node, failed_task):
        if node.get('run') is not None:
            finish_run_if_done(node['run'], failed_task)

    def model_software(self):
        return {'name': self.model_name, 'version': get_model_version(self.model_name), 'type': 'model'}


class ModelPredictionStep(BaseModelStep, LocalStep):
    """A model that runs in Cocos, with its adapter."""

    def software(self, task):
        """The model, its version and the SHA-256 of its weights: the files its descriptor declares for
        each antibiotic it predicted, and those for all of them (without antibiotic), if any."""
        weights = []
        for antibiotic in task.parameters.get('antibiotics', []) + ['']:
            for path in get_model_weights(self.model_name, antibiotic):
                if path.is_file():
                    entry = {'antibiotic': antibiotic} if antibiotic else {}
                    weights.append({**entry, 'sha256': _weights_sha256(path, os.path.getmtime(path))})
        return [{**self.model_software(), 'weights': weights}]

    def expected_software(self):
        return [self.model_software()]

    def process(self, task):
        """Predict every antibiotic of the task; antibiotics that fail get NO_RESULT."""
        genes = task.input_file('genes')
        results = {}
        for antibiotic in task.parameters['antibiotics']:
            try:
                results[antibiotic] = as_result(get_prediction(self.model_name, antibiotic, genes))
            except Exception:
                logger.exception('Prediction failed for model=%s, antibiotic=%s', self.model_name, antibiotic)
                results[antibiotic] = NO_RESULT

        predicted_nothing = bool(results) and all(value == NO_RESULT for value in results.values())
        _save_results(task, self.model_name, results, with_csv=not predicted_nothing)
        if predicted_nothing:
            raise StepError(f'The model {self.model_name} could not predict any of the selected antibiotics.')


class RemoteModelPredictionStep(BaseModelStep, ExternalStep):
    """A model that runs in a service (see prediction.remote): its input files are sent there as a job.

    The service says what each result is about with an ARO term, which becomes the name of the
    antibiotic in Cocos; results about other terms (e.g. a class of antibiotics) are left out. The
    output of the tool itself is kept as the output `tool_output`, if the descriptor declares it.
    """
    RAW_OUTPUT = 'tool_output'

    @property
    def endpoint(self):
        return get_model_endpoint(self.model_name)

    @property
    def service_name(self):
        """The name of the model in its service: the last part of its endpoint (predict/<name>)."""
        return self.endpoint.rstrip('/').rsplit('/', 1)[-1]

    def process(self, task):
        files = {}
        for port in self.consumes:
            file = task.input_file(port.role)
            with file.file.open('rb') as content:
                files[port.role] = (Path(file.file.name).name, content.read())
        job_id = remote.submit(self.endpoint, files, task.process.organism or None)
        return Started(job_id) if job_id else Busy()

    def job_status(self, job_id):
        job = remote.get_job(self.endpoint, job_id)
        return (None, 404) if job is None else (job['status'], 200)

    def job_failure(self, job_id):
        job = remote.get_job(self.endpoint, job_id) or {}
        return job.get('message') or 'External job failed', job.get('error_kind') == 'input'

    def collect(self, task):
        by_antibiotic = {_antibiotic_label(result['about']): result
                         for result in remote.get_result(self.endpoint, task.external_job_id)}
        results = {}
        for antibiotic in task.parameters['antibiotics']:
            result = by_antibiotic.get(antibiotic)
            try:
                results[antibiotic] = as_result({key: value for key, value in result.items() if key != 'about'})
            except (AttributeError, ValueError):
                results[antibiotic] = NO_RESULT  # nothing about it, or not a valid result
        _save_results(task, self.model_name, results)

        if any(port.role == self.RAW_OUTPUT for port in self.produces) and not self.already_saved(task, self.RAW_OUTPUT):
            raw = remote.get_raw_output(self.endpoint, task.external_job_id)
            if raw:
                name, content = raw
                task.save_output(self.RAW_OUTPUT, content, self.output_port(self.RAW_OUTPUT).format,
                                 f'{self.model_name}_{task.id}_{name}')

    def already_saved(self, task, role):
        # collect() may be retried after a partial failure: keep what was already stored.
        return task.task_outputs.filter(role=role).exists()

    def software(self, task):
        """The model and what its job used, as the service recorded it."""
        job = remote.get_job(self.endpoint, task.external_job_id) if task.external_job_id else None
        return [self.model_software()] + ((job or {}).get('software') or [])

    def expected_software(self):
        models = remote.installed_models(self.endpoint)
        if models is None or self.service_name not in models:
            return None
        return [self.model_software()] + models[self.service_name].get('software', [])


def _antibiotic_label(curie):
    """The name in Cocos (its ARO label, e.g. 'amikacin') of an ARO term given as 'ARO:0000013'."""
    label = terms_graph().value(OBO[curie.replace(':', '_')], RDFS.label)
    return str(label) if label is not None else None


def _save_results(task, model_name, results, with_csv=True):
    """Keep the results of a task and, unless with_csv is False, its CSV (the output `predictions`)."""
    task.results = results
    task.save(update_fields=['results', 'updated_at'])
    if with_csv and not task.task_outputs.filter(role='predictions').exists():
        task.save_output('predictions', _results_csv(results), File.FileType.CSV,
                         f'prediction_{task.id}_{model_name}.csv')


def _results_csv(results):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['antibiotic', 'probability', 'call'])
    for antibiotic, result in results.items():
        if result == NO_RESULT:
            writer.writerow([antibiotic, '', ''])
            continue
        score, call = result.get('score'), result.get('call')
        writer.writerow([antibiotic, '' if score is None else round(score, 4), CALLS[call] if call else ''])
    return output.getvalue().encode('utf-8')


@register_step_provider
def model_prediction_steps():
    steps = ((RemoteModelPredictionStep if get_model_endpoint(name) else ModelPredictionStep)(name)
             for name in list_registered_models())
    return {step.key: step for step in steps}
