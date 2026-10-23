"""Model registry utilities. Allow registering model adapter classes with a simple decorator and retrieving them by name.

What a model supports (organisms, antibiotics, input) comes from its descriptor.ttl, read by the
semantic layer when the model is registered.
"""
import inspect
from pathlib import Path

from semantics.registry.plugins import DescriptorError, accept_plugin, describe_model, reject_plugin

MODEL_REGISTRY = {
    # 'model_name': ModelAdapterClass,
}

MODEL_ANTIBIOTICS = {
    # 'model_name': ['antibiotic1', 'antibiotic2', ...],
}


class _AnyOrganism:
    """Declares that a model works for samples of any organism."""
    def __repr__(self):
        return 'ANY_ORGANISM'

ANY_ORGANISM = _AnyOrganism()

MODEL_ORGANISMS = {
    # 'model_name': ANY_ORGANISM or {'NCBITaxon:562': 'Escherichia coli', ...},
}

MODEL_PORTS = {
    # 'model_name': (consumes, produces), tuples of core.steps.Port
}

MODEL_VERSIONS = {
    # 'model_name': '1.0.0', from the descriptor
}

def _validate_adapter_init(cls) -> None:
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        raise TypeError(f"Cannot inspect __init__ of adapter {cls!r}")

    params = [p for p in sig.parameters.values() if p.name != 'self']
    names = {p.name for p in params}
    if 'antibiotic' not in names:
        raise TypeError(
            f"Adapter {cls.__name__} must accept an 'antibiotic' parameter in __init__"
        )

def register_model(name: str = None):
    """Register an adapter. The model is skipped (and reported by the system checks) if its
    descriptor is missing or invalid, or if an antibiotic it declares has no weights."""
    def _decorator(cls):
        _validate_adapter_init(cls)
        key = (name or cls.__name__).lower()
        try:
            description = describe_model(key)
            missing = sorted(set(description.antibiotics) - set(list_model_weights(key)))
            if missing:
                raise DescriptorError(f'it declares {", ".join(missing)} but has no weights for them in {model_weights_dir(key)}')
        except DescriptorError as error:
            reject_plugin('model', key, error)
            return cls
        accept_plugin('model', key)
        MODEL_REGISTRY[key] = cls
        MODEL_ANTIBIOTICS[key] = list(description.antibiotics)
        MODEL_ORGANISMS[key] = ANY_ORGANISM if description.any_organism else description.organisms
        MODEL_PORTS[key] = (description.inputs, description.outputs)
        MODEL_VERSIONS[key] = description.version
        return cls
    return _decorator

def get_model_adapter_class(name: str):
    key = name.lower() if name else ''
    if key not in MODEL_REGISTRY:
        return None
    return MODEL_REGISTRY[key]

# ---- Public API for views
def list_registered_models():
    return list(MODEL_REGISTRY.keys())

def get_model_supported_antibiotics(name: str):
    """Return list of antibiotic names available for a given registered model."""
    return MODEL_ANTIBIOTICS.get(name.lower(), [])

def get_model_ports(name: str):
    """Return (consumes, produces) of a registered model, as declared in its descriptor."""
    return MODEL_PORTS[name.lower()]

def get_model_version(name: str):
    """Return the version of a registered model, as declared in its descriptor."""
    return MODEL_VERSIONS.get(name.lower(), '')

def get_model_supported_organisms(name: str):
    """Return ANY_ORGANISM or {CURIE: name} of the organisms a registered model supports."""
    organisms = MODEL_ORGANISMS.get(name.lower(), ANY_ORGANISM)
    return organisms if organisms is ANY_ORGANISM else dict(organisms)

def list_all_organisms():
    """Return (CURIE, name) pairs of the organisms some model specifically supports, sorted by name."""
    organisms = {}
    for model_organisms in MODEL_ORGANISMS.values():
        if model_organisms is not ANY_ORGANISM:
            organisms.update(model_organisms)
    return sorted(organisms.items(), key=lambda item: item[1])

def list_all_antibiotics():
    """Return sorted list of all antibiotic names available across all registered models."""
    antibiotics = set()
    for ab_list in MODEL_ANTIBIOTICS.values():
        antibiotics.update(ab_list)
    return sorted(antibiotics)

# ---- Weights
def model_weights_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / 'ai_models' / name / 'weights'

def list_model_weights(name: str):
    """Return the sorted names of the weight files (<antibiotic>.pt) of a model."""
    weights_dir = model_weights_dir(name)
    return sorted(p.stem for p in weights_dir.glob('*.pt')) if weights_dir.is_dir() else []
