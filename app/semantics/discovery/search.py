"""How discovery decides, in three levels:

1. verdict(): for one model, check its organism and antibiotics, then whether the sample already has
   its inputs (ready) or some steps can produce them (reachable).
2. shortest_preparation(): breadth-first search of those steps: every path of 1 step, then of 2...
   The first level that reaches the inputs of the model has the shortest paths; among them, the
   cheapest (Path.cost) wins.
3. assign(): whether some data satisfies the inputs of a step or model. A piece of data satisfies an
   input if its data and format are the requested ones or kinds of them, and its sequencing
   technique is the requested one, if any.
"""
from dataclasses import dataclass

from ..namespaces import OBO
from .graphs import Item, is_a, label, read_sample, read_tools
from .results import Compatibility, PlannedStep, Source, Status

# A model for Bacteria accepts a sample of any organism (v1: no other taxonomy reasoning).
ANY_BACTERIA = OBO.NCBITaxon_2
MAX_STEPS = 6


def discover(registry, sample, antibiotics=None):
    """Return the Compatibility of every model of `registry` (a graph) with `sample` (a graph).

    `antibiotics`, if given, are the names of the antibiotics the user wants: a model that
    predicts none of them is incompatible.
    """
    tools = read_tools(registry)
    steps = [tool for tool in tools if not tool.is_model]
    items, organism = read_sample(sample)
    return [verdict(model, steps, items, organism, antibiotics, registry) for model in tools if model.is_model]


# --- 1. The verdict for one model

def verdict(model, steps, items, organism, antibiotics, registry):
    reasons = organism_reasons(model, organism, registry) + antibiotic_reasons(model, antibiotics)

    inputs = assign(model.inputs, items, registry)
    if inputs is not None:
        status, path = Status.READY, Path(items=items)
    else:
        path, inputs = shortest_preparation(model, steps, items, registry)
        status = Status.REACHABLE
        if path is None:
            reasons.append(data_reason(model, registry))

    if reasons:
        return Compatibility(model.identifier, Status.INCOMPATIBLE, reasons=tuple(reasons))
    return Compatibility(model.identifier, status, steps=path.steps, inputs=tuple(inputs))


def organism_reasons(model, organism, registry):
    if ANY_BACTERIA in model.organisms:
        return []
    names = ', '.join(sorted(model.organisms.values()))
    if organism is None:
        return [f'This model is only for {names}, and the organism of this sample is unknown.']
    if organism not in model.organisms:
        return [f'This model is only for {names}, and this sample is {label(registry, organism)}.']
    return []


def antibiotic_reasons(model, antibiotics):
    if antibiotics and not model.antibiotics & set(antibiotics):
        return ['This model predicts none of the selected antibiotics.']
    return []


def data_reason(model, registry):
    needed = ', '.join(f'{label(registry, p.kind.data)} ({label(registry, p.kind.format)})' for p in model.inputs)
    return f'This model needs {needed}, and no steps can obtain it from the data of this sample.'


# --- 2. The search for the shortest preparation

@dataclass(frozen=True)
class Path:
    """Some steps applied to the sample, and the data there is after them."""
    items: tuple
    steps: tuple = ()     # PlannedStep
    recomputed: int = 0   # outputs that were already available
    jobs: int = 0         # steps run in the bio service

    def kinds(self):
        return {item.kind for item in self.items}

    def extend(self, step, inputs):
        """This path followed by `step`, which takes `inputs` ((role, Source) pairs)."""
        index = len(self.steps)
        kinds = self.kinds()
        return Path(
            items=self.items + tuple(Item(output.kind, Source(output.role, step=index)) for output in step.outputs),
            steps=self.steps + (PlannedStep(step.identifier, tuple(inputs)),),
            recomputed=self.recomputed + sum(output.kind in kinds for output in step.outputs),
            jobs=self.jobs + step.web_service,
        )

    def cost(self):
        """Fewest steps, then least recomputed data, then fewest bio service jobs, then by identifiers."""
        return (len(self.steps), self.recomputed, self.jobs, tuple(step.step for step in self.steps))


def shortest_preparation(model, steps, items, registry):
    """(path, model inputs) of the cheapest shortest path of steps that gives `model` its inputs,
    or (None, None) if there is none within MAX_STEPS.

    A step is only tried if its inputs are available and it produces some kind of data the path
    does not have yet; paths that end with the same kinds of data as a shorter one are dropped.
    """
    level = [Path(items=items)]
    seen = {frozenset(level[0].kinds())}
    for _ in range(MAX_STEPS):
        next_level, found = [], []
        for path in level:
            for step in steps:
                inputs = assign(step.inputs, path.items, registry)
                if inputs is None or step_adds_nothing(step, path):
                    continue
                longer = path.extend(step, inputs)
                model_inputs = assign(model.inputs, longer.items, registry)
                if model_inputs is not None:
                    found.append((longer, model_inputs))
                elif frozenset(longer.kinds()) not in seen:
                    next_level.append(longer)
        if found:
            return min(found, key=lambda entry: entry[0].cost())
        seen |= {frozenset(path.kinds()) for path in next_level}
        level = next_level
    return None, None


def step_adds_nothing(step, path):
    kinds = path.kinds()
    return all(output.kind in kinds for output in step.outputs)


# --- 3. Matching data to inputs

def assign(parameters, items, registry):
    """Give each parameter a different item that satisfies it: [(role, Source), ...], or None.

    Items with the same role as the parameter, then items produced by the path (the latest
    first), are preferred.
    """
    used, assigned = set(), []
    for parameter in parameters:
        candidates = [index for index, item in enumerate(items)
                      if index not in used and satisfies(item.kind, parameter.kind, registry)]
        if not candidates:
            return None
        best = max(candidates, key=lambda index: (items[index].source.role == parameter.role,
                                                  items[index].source.step is not None, index))
        used.add(best)
        assigned.append((parameter.role, items[best].source))
    return assigned


def satisfies(offered, required, registry):
    if required.technique is not None and offered.technique != required.technique:
        return False
    return is_a(registry, offered.data, required.data) and is_a(registry, offered.format, required.format)
