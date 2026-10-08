"""Prediction steps: one step per registered prediction model, resolved from the model registry."""
from core.models import File
from core.steps import DataKind, LocalStep, Port, register_step_provider

from .registry import get_model_supported_antibiotics, list_registered_models

PREDICTION_STEP_PREFIX = 'predict_'


class ModelPredictionStep(LocalStep):
    """Predict antibiotic resistance with one registered model."""
    category = 'prediction'
    consumes = (Port('genes', DataKind.GENE_SET, File.FileType.JSON),)
    produces = (Port('predictions', DataKind.RESISTANCE_PREDICTION, None),)
    default_parameters = {'antibiotics': []}

    def __init__(self, model_name):
        self.model_name = model_name
        self.key = f'{PREDICTION_STEP_PREFIX}{model_name}'
        self.label = model_name

    @property
    def supported_antibiotics(self):
        return get_model_supported_antibiotics(self.model_name)


@register_step_provider
def model_prediction_steps():
    steps = (ModelPredictionStep(name) for name in list_registered_models())
    return {step.key: step for step in steps}
