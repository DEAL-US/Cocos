"""What discover() returns: one Compatibility per model."""
from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    READY = 'ready'
    REACHABLE = 'reachable'
    INCOMPATIBLE = 'incompatible'


@dataclass(frozen=True)
class Source:
    """Where an input comes from: a file of the sample (`file`, its id), or an output of an earlier
    step of the preparation (`step`, its position). `role` is the role of that file or output."""
    role: str
    file: str | None = None
    step: int | None = None


@dataclass(frozen=True)
class PlannedStep:
    """A preparation step to run, with where each of its inputs comes from."""
    step: str       # step identifier, e.g. 'bakta_annotation'
    inputs: tuple   # ((input role, Source), ...)


@dataclass(frozen=True)
class Compatibility:
    """The verdict for one model."""
    model: str
    status: Status
    steps: tuple = ()     # PlannedStep, in order (reachable only)
    inputs: tuple = ()    # ((input role, Source), ...) of the model (ready or reachable)
    reasons: tuple = ()   # why not (incompatible only)
