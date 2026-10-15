"""System checks: every antibiotic a model descriptor declares needs its weights file."""
from django.core.checks import Error, Warning, register

from .adapters.registry import get_model_supported_antibiotics, list_model_weights, list_registered_models, model_weights_dir


@register()
def check_model_weights(app_configs, **kwargs):
    messages = []
    for name in list_registered_models():
        declared = set(get_model_supported_antibiotics(name))
        weights = set(list_model_weights(name))
        for antibiotic in sorted(declared - weights):
            messages.append(Error(
                f'Model {name} declares {antibiotic} but has no weights for it.',
                hint=f'Add {model_weights_dir(name) / (antibiotic + ".pt")} or remove the antibiotic from its descriptor.',
                id='prediction.E001',
            ))
        for antibiotic in sorted(weights - declared):
            messages.append(Warning(
                f'Model {name} has weights for {antibiotic}, which its descriptor does not declare: it is not offered.',
                id='prediction.W001',
            ))
    return messages
