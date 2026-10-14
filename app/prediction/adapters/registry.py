"""Model registry utilities. Allow registering model adapter classes with a simple decorator and retrieving them by name."""
import inspect
import re
from pathlib import Path

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

NCBI_TAXON_CURIE = re.compile(r'^NCBITaxon:\d+$')

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

def _validate_supported_organisms(cls):
    """Return ANY_ORGANISM or a {CURIE: name} dict; adapters that declare nothing support any organism."""
    organisms = getattr(cls, 'supported_organisms', ANY_ORGANISM)
    if organisms is ANY_ORGANISM:
        return ANY_ORGANISM
    if not isinstance(organisms, dict) or not organisms:
        raise TypeError(f"Adapter {cls.__name__}.supported_organisms must be ANY_ORGANISM or a non-empty dict {{CURIE: name}}")
    for curie, label in organisms.items():
        if not NCBI_TAXON_CURIE.match(curie) or not label:
            raise TypeError(f"Adapter {cls.__name__}: invalid organism {curie!r}; use 'NCBITaxon:<id>': '<name>'")
    return dict(organisms)

def register_model(name: str = None):
    def _decorator(cls):
        _validate_adapter_init(cls)
        organisms = _validate_supported_organisms(cls)
        key = (name or cls.__name__).lower()
        base_dir = Path(__file__).resolve().parents[2]
        weights_dir = base_dir / 'ai_models' / key / 'weights'
        MODEL_REGISTRY[key] = cls
        MODEL_ANTIBIOTICS[key] = _compute_model_supported_antibiotics(weights_dir)
        MODEL_ORGANISMS[key] = organisms
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

# ---- Internal utilities
def _compute_model_supported_antibiotics(weights_dir: str):
    """
    Compute the list of antibiotic names available for a given registered model.
    """
    if weights_dir.exists() and weights_dir.is_dir():
        return sorted({p.stem for p in weights_dir.glob('*.pt')})
    else:
        return []