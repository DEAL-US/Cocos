"""Test helpers: register fake prediction models for the duration of a test."""
from core.models import File
from core.steps import DataKind, Port

from .adapters.registry import MODEL_ANTIBIOTICS, MODEL_ORGANISMS, MODEL_PORTS, MODEL_REGISTRY

# What the descriptor of a fake model declares: the genes of an annotation in, a CSV out.
FAKE_MODEL_PORTS = ((Port('genes', DataKind.GENE_SET, File.FileType.JSON),),
                    (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),))

_REGISTRIES = (MODEL_REGISTRY, MODEL_ANTIBIOTICS, MODEL_ORGANISMS, MODEL_PORTS)


def register_fake_models(test, models):
    """Register `models` ({name: adapter class or (adapter class, antibiotics)}) until `test` ends.

    The registries are restored afterwards, so the fakes do not leak into other tests.
    """
    backups = [dict(registry) for registry in _REGISTRIES]

    def restore():
        for registry, backup in zip(_REGISTRIES, backups):
            registry.clear()
            registry.update(backup)
    test.addCleanup(restore)

    for name, model in models.items():
        cls, antibiotics = model if isinstance(model, tuple) else (model, [])
        MODEL_REGISTRY[name] = cls
        MODEL_ANTIBIOTICS[name] = list(antibiotics)
        MODEL_PORTS[name] = FAKE_MODEL_PORTS
