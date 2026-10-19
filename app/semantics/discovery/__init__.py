"""Discovery: which models can run on a sample, decided only from RDF.

For each model of the registry, discover() answers one of:

- ready: the sample already has every input of the model;
- reachable: some preparation steps (assembly, annotation...) produce the missing inputs;
- incompatible: nothing gets there, or the model is not for the organism of the sample, or it
  predicts none of the requested antibiotics.

It is split in three modules:

- results.py: what discover() returns;
- graphs.py: what it reads from the registry and sample graphs (with SPARQL);
- search.py: how it decides (matching data to inputs, and a breadth-first search of steps).
"""
from .results import Compatibility, PlannedStep, Source, Status
from .search import discover

__all__ = ['Compatibility', 'PlannedStep', 'Source', 'Status', 'discover']
