"""Prediction steps: one step per registered prediction model, resolved from the model registry."""
import csv
import io
import logging

from core.models import File
from core.steps import DataKind, LocalStep, Port, StepError, register_step_provider

from .models import PredictionTask
from .prediction import NO_RESULT, get_prediction
from .runs import finish_run_if_done, mark_run_started
from .registry import get_model_supported_antibiotics, get_model_supported_organisms, list_registered_models

logger = logging.getLogger(__name__)

PREDICTION_STEP_PREFIX = 'predict_'


class ModelPredictionStep(LocalStep):
    """Predict antibiotic resistance with one registered model."""
    category = 'prediction'
    task_model = PredictionTask
    consumes = (Port('genes', DataKind.GENE_SET, File.FileType.JSON),)
    produces = (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),)
    default_parameters = {'antibiotics': []}

    def __init__(self, model_name):
        self.model_name = model_name
        self.key = f'{PREDICTION_STEP_PREFIX}{model_name}'
        self.label = model_name

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

    def process(self, task):
        """Predict every antibiotic of the task; antibiotics that fail get NO_RESULT."""
        genes = task.input_file('genes')
        results = {}
        for antibiotic in task.parameters['antibiotics']:
            try:
                results[antibiotic] = float(get_prediction(self.model_name, antibiotic, genes))
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
    writer.writerow(['antibiotic', 'probability'])
    for antibiotic, value in results.items():
        writer.writerow([antibiotic, '' if value == NO_RESULT else round(value, 4)])
    return output.getvalue().encode('utf-8')


@register_step_provider
def model_prediction_steps():
    steps = (ModelPredictionStep(name) for name in list_registered_models())
    return {step.key: step for step in steps}
