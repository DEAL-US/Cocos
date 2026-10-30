"""Prediction steps: one step per registered prediction model, resolved from the model registry."""
import csv
import io
import logging
import os
from functools import lru_cache

from core.models import File
from core.utils import sha256_of
from core.steps import LocalStep, StepError, register_step_provider

from .adapters.registry import (
    get_model_adapter_class,
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


class ModelPredictionStep(LocalStep):
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

    def software(self, task):
        """The model, its version and the SHA-256 of its weights: the files its descriptor declares for
        each antibiotic it predicted, and those for all of them (without antibiotic), if any."""
        weights = []
        for antibiotic in task.parameters.get('antibiotics', []) + ['']:
            for path in get_model_weights(self.model_name, antibiotic):
                if path.is_file():
                    entry = {'antibiotic': antibiotic} if antibiotic else {}
                    weights.append({**entry, 'sha256': _weights_sha256(path, os.path.getmtime(path))})
        return [{'name': self.model_name, 'version': get_model_version(self.model_name), 'type': 'model',
                 'weights': weights}]

    def expected_software(self):
        return [{'name': self.model_name, 'version': get_model_version(self.model_name), 'type': 'model'}]

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

        task.results = results
        task.save(update_fields=['results', 'updated_at'])

        if results and all(value == NO_RESULT for value in results.values()):
            raise StepError(f'The model {self.model_name} could not predict any of the selected antibiotics.')

        task.save_output('predictions', _results_csv(results), File.FileType.CSV, f'prediction_{task.id}_{self.model_name}.csv')


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
    steps = (ModelPredictionStep(name) for name in list_registered_models())
    return {step.key: step for step in steps}
