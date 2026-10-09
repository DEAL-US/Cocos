"""Pipeline steps: the operations a process can run, either a conversion or a prediction.

Each step declares what it consumes and produces as ports (role, kind of data, file format),
so a process can be planned as a chain of steps whose outputs feed the next step's inputs.

Steps are registered with `@register_step`. Steps that depend on other registries (one
prediction step per model) are provided on demand with `register_step_provider`.
"""
import copy
from dataclasses import dataclass
from enum import StrEnum

from core.models import File


class DataKind(StrEnum):
    """What a piece of data represents, independently of its file format."""
    READS = 'reads'
    ASSEMBLY = 'assembly'
    ANNOTATED_GENOME = 'annotated_genome'
    GENE_SET = 'gene_set'
    RESISTANCE_PREDICTION = 'resistance_prediction'


@dataclass(frozen=True)
class Port:
    """An input or output of a step.

    `role` names it within the step (e.g. 'r1' and 'r2' are both reads, but not interchangeable),
    `kind` says what the data represents and `format` (a File.FileType) how it is stored.
    """
    role: str
    kind: DataKind
    format: str | None


class UnknownStepError(KeyError):
    pass


class Step:
    """Base class for every step. Subclasses only declare metadata here."""
    key: str = ''
    label: str = ''
    category: str = ''
    consumes: tuple[Port, ...] = ()
    produces: tuple[Port, ...] = ()
    default_parameters: dict = {}
    is_external = False

    def input_port(self, role):
        return _find_port(self.consumes, role, self.key)

    def output_port(self, role):
        return _find_port(self.produces, role, self.key)

    def build_parameters(self, overrides=None):
        """Return the step parameters: defaults updated with `overrides`. Unknown names are rejected."""
        overrides = dict(overrides or {})
        unknown = set(overrides) - set(self.default_parameters)
        if unknown:
            raise ValueError(f"Unknown parameters for step {self.key}: {', '.join(sorted(unknown))}")
        return {**copy.deepcopy(self.default_parameters), **overrides}

    def __repr__(self):
        return f"<{type(self).__name__} {self.key}>"


class LocalStep(Step):
    """A step that runs inside the application."""


class ExternalStep(Step):
    """A step that runs as a job in an external service (the bio service)."""
    is_external = True


def _find_port(ports, role, step_key):
    for port in ports:
        if port.role == role:
            return port
    raise KeyError(f"Step {step_key} has no port {role!r}")


# --- Registry
_STEPS = {}
_PROVIDERS = []


def validate_step(step):
    """Check that a step declares the metadata every step needs."""
    for attribute in ('key', 'label', 'category'):
        if not getattr(step, attribute):
            raise TypeError(f"{type(step).__name__} must define '{attribute}'")

    for ports in (step.consumes, step.produces):
        roles = [port.role for port in ports]
        if len(roles) != len(set(roles)):
            raise TypeError(f"Step {step.key} declares the same role twice: {roles}")
        for port in ports:
            if not isinstance(port.kind, DataKind):
                raise TypeError(f"Step {step.key}: port {port.role!r} has an unknown data kind")
            if port.format is not None and port.format not in File.FileType.values:
                raise TypeError(f"Step {step.key}: port {port.role!r} has an unknown format {port.format!r}")


def register_step(cls):
    """Class decorator: register one instance of the step under its key."""
    step = cls()
    validate_step(step)
    if step.key in _STEPS:
        raise ValueError(f"A step is already registered with key {step.key!r}")
    _STEPS[step.key] = step
    return cls


def register_step_provider(provider):
    """Register a callable returning {key: step} for steps created on demand."""
    _PROVIDERS.append(provider)
    return provider


def list_steps():
    """Return every available step, registered and provided."""
    steps = dict(_STEPS)
    for provider in _PROVIDERS:
        for key, step in provider().items():
            steps.setdefault(key, step)
    return list(steps.values())


def get_step(key):
    if key in _STEPS:
        return _STEPS[key]
    for provider in _PROVIDERS:
        step = provider().get(key)
        if step is not None:
            return step
    raise UnknownStepError(key)
