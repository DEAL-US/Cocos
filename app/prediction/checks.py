"""System checks: weights a model has but its descriptor does not declare.

Declared antibiotics without weights keep the model from registering (see register_model).
"""
from django.core.checks import Warning, register

from .adapters.registry import get_model_supported_antibiotics, list_model_weights, list_registered_models


@register()
def check_model_weights(app_configs, **kwargs):
    return [
        Warning(
            f'Model {name} has weights for {antibiotic}, which its descriptor does not declare: it is not offered.',
            id='prediction.W001',
        )
        for name in list_registered_models()
        for antibiotic in sorted(set(list_model_weights(name)) - set(get_model_supported_antibiotics(name)))
    ]
