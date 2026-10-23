"""Pipeline steps: the operations a process can run, either a conversion or a prediction.

Each step declares what it consumes and produces as ports (role, kind of data, file format),
so a process can be planned as a chain of steps whose outputs feed the next step's inputs.

Steps are registered with `@register_step`. Steps that depend on other registries (one
prediction step per model) are provided on demand with `register_step_provider`.
"""
import copy
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings

# Module import: core.models imports this module at load time.
from core import models as core_models


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


class StepError(Exception):
    """An expected failure of a step; its message is shown to the user."""


@dataclass(frozen=True)
class Started:
    """An external job was accepted by the service."""
    job_id: str


@dataclass(frozen=True)
class Busy:
    """The external service could not accept the job now; try again later."""


def cocos_software():
    """The entry of Cocos itself in the software of a task."""
    return {'name': 'Cocos', 'version': settings.COCOS_VERSION, 'type': 'tool'}


def software_label(entry):
    """How an entry of Task.software is shown: 'Bakta 1.12.1', 'Bakta database 6.0 (light)'."""
    label = f"{entry['name']} {entry.get('version', '')}".strip()
    return f"{label} ({entry['variant']})" if entry.get('variant') else label


def used_software_labels(task):
    """What a finished task used, for people: its tools and databases first, Cocos last."""
    entries = sorted(task.software, key=lambda entry: entry.get('name') == 'Cocos')
    return [software_label(entry) for entry in entries]


def software_labels(entries):
    """The labels of some software entries (e.g. Step.expected_software()), or None if unknown."""
    return None if entries is None else [software_label(entry) for entry in entries]


class Step:
    """Base class for every step: metadata, plus how it runs (see LocalStep and ExternalStep)."""
    key: str = ''
    label: str = ''
    # One sentence on what the step does, for its RDF description.
    description: str = ''
    category: str = ''
    consumes: tuple[Port, ...] = ()
    produces: tuple[Port, ...] = ()
    default_parameters: dict = {}
    is_external = False
    # Task subclass used for the tasks of this step; None means core.models.Task.
    task_model = None

    def input_port(self, role):
        return _find_port(self.consumes, role, self.key)

    def output_port(self, role):
        return _find_port(self.produces, role, self.key)

    def on_task_started(self, task):
        """Hook called when a task of this step starts running."""

    def on_task_finished(self, task):
        """Hook called when a task of this step completes or fails."""

    def software(self, task):
        """The tools, databases or models a finished task of this step used, besides Cocos itself,
        as dicts with at least 'name', 'version' and 'type' (see Task.software)."""
        return []

    def expected_software(self):
        """What a new task of this step would use, besides Cocos (like `software`), or None if it
        cannot be known now (e.g. the bio service does not answer)."""
        return []

    # Whether a node of this step is cancelled when a node it depends on fails (see core.tasks).
    cancel_when_blocked = False

    def on_node_cancelled(self, process, node, failed_task):
        """Hook called when a node of this step is cancelled because `failed_task` failed."""

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

    def process(self, task):
        """Do the whole work: read the task inputs and store its outputs. Raise StepError on failure."""
        raise NotImplementedError


class ExternalStep(Step):
    """A step that runs as a job in an external service (the bio service).

    `process` submits the job and returns at once; the job is then polled with `job_status`,
    and `collect` stores the outputs once the service reports `finished_status`.
    """
    is_external = True
    finished_status = 'completed'

    def process(self, task):
        """Submit the job. Return Started(job_id), or Busy if the service cannot take it now."""
        raise NotImplementedError

    def job_status(self, job_id):
        """Return (status, http_code) of the job in the external service."""
        raise NotImplementedError

    def collect(self, task):
        """Download the job results and store them as the task outputs."""
        raise NotImplementedError

    def task_status(self, external_status):
        """Map a status reported by the service to the TaskStatus of a task of this step.

        Only `finished_status` (or a generic 'completed') finishes the task: intermediate
        statuses, such as 'assembled' in an assembly that also annotates, mean it is running.
        """
        TaskStatus = core_models.TaskStatus
        if external_status == 'failed':
            return TaskStatus.FAILED
        if external_status in (self.finished_status, 'completed'):
            return TaskStatus.COMPLETED
        return TaskStatus.RUNNING


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
            if port.format is not None and port.format not in core_models.File.FileType.values:
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
