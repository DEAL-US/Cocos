"""Model registry utilities. Allow registering model adapter classes with a simple decorator and retrieving them by name.

What a model supports (organisms, antibiotics, input) comes from its descriptor.ttl, read by the
semantic layer when the model is registered.
"""
import inspect
from pathlib import Path

from semantics.registry.plugins import DescriptorError, accept_plugin, check_files, describe_model, reject_plugin

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

MODEL_DATA_ORGANISMS = {
    # 'model_name': {'NCBITaxon:28901': 'Salmonella enterica', ...}: organisms its data has measurements about
}

MODEL_WEIGHTS = {
    # 'model_name': (('amikacin', 'weights/amikacin.pt'), ('', 'shared.pt'), ...): files the descriptor declares, by antibiotic
}

MODEL_ENDPOINTS = {
    # 'model_name': 'predict/amrfinderplus': where the jobs of a model that runs in a service are sent
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
    descriptor is missing or invalid, or if a file it declares (with its SHA-256) is missing or
    changed. It needs no weights: how it predicts is up to its adapter."""
    def _decorator(cls):
        _validate_adapter_init(cls)
        key = (name or cls.__name__).lower()
        _register(key, cls)
        return cls
    return _decorator


def register_remote_model(name: str):
    """Register a model that runs in a service: its folder has only its descriptor, which says where
    its jobs are sent (schema:potentialAction). Skipped and reported like any other model."""
    _register(name.lower(), None)


def _register(key, cls):
    """Register the model `key` from its descriptor: with its adapter `cls`, or None if it runs in a service."""
    try:
        description = describe_model(key)
        check_files(model_dir(key), description.files)
        if cls is not None and description.endpoint:
            raise DescriptorError('it has an adapter, so it runs in Cocos, but its descriptor says it runs in a service')
        if cls is None and not description.endpoint:
            raise DescriptorError('it has no adapter, so its descriptor must say where it runs (schema:potentialAction)')
    except DescriptorError as error:
        reject_plugin('model', key, error)
        return
    accept_plugin('model', key)
    MODEL_REGISTRY[key] = cls
    MODEL_ANTIBIOTICS[key] = list(description.antibiotics)
    MODEL_ORGANISMS[key] = ANY_ORGANISM if description.any_organism else description.organisms
    MODEL_PORTS[key] = (description.inputs, description.outputs)
    MODEL_VERSIONS[key] = description.version
    MODEL_DATA_ORGANISMS[key] = description.data_organisms
    MODEL_WEIGHTS[key] = description.weights
    MODEL_ENDPOINTS[key] = description.endpoint

def get_model_endpoint(name: str):
    """Where the jobs of a model that runs in a service are sent, or '' if it runs in Cocos."""
    return MODEL_ENDPOINTS.get(name.lower(), '')

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
    """Return (CURIE, name) pairs of the organisms Cocos knows something about, sorted by name: those
    some model specifically supports, and those the data of some model (e.g. its training data) has
    measurements about. Their hierarchy is in terms.ttl."""
    organisms = {}
    for model_organisms in MODEL_ORGANISMS.values():
        if model_organisms is not ANY_ORGANISM:
            organisms.update(model_organisms)
    for data_organisms in MODEL_DATA_ORGANISMS.values():
        organisms.update(data_organisms)
    return sorted(organisms.items(), key=lambda item: item[1])

def list_all_antibiotics():
    """Return sorted list of all antibiotic names available across all registered models."""
    antibiotics = set()
    for ab_list in MODEL_ANTIBIOTICS.values():
        antibiotics.update(ab_list)
    return sorted(antibiotics)

# ---- Files
def model_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / 'ai_models' / name

def get_model_weights(name: str, antibiotic: str):
    """Return the paths of the files the descriptor of a registered model declares for `antibiotic`
    (e.g. its weights), or for all of them if `antibiotic` is ''; none if it declares none, as a
    rule-based model."""
    return [model_dir(name) / path for about, path in MODEL_WEIGHTS.get(name.lower(), ()) if about == antibiotic]
