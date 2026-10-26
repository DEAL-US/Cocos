"""Test helpers: register fake prediction models for the duration of a test."""
from unittest import mock

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from core.models import File
from core.steps import DataKind, Port
from semantics.namespaces import BIOSCHEMAS, BSC, EDAM, OBO, SCHEMA
from semantics.registry.descriptors import model_iri
from semantics.registry.mappings import data_term, format_term

from . import services
from .adapters.registry import (MODEL_ANTIBIOTICS, MODEL_DATA_ORGANISMS, MODEL_ORGANISMS, MODEL_PORTS, MODEL_REGISTRY,
                                MODEL_VERSIONS)

# What the descriptor of a fake model declares: the genes of an annotation in, a CSV out.
FAKE_MODEL_PORTS = ((Port('genes', DataKind.GENE_SET, File.FileType.JSON),),
                    (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),))

_REGISTRIES = (MODEL_REGISTRY, MODEL_ANTIBIOTICS, MODEL_ORGANISMS, MODEL_PORTS, MODEL_VERSIONS, MODEL_DATA_ORGANISMS)
FAKE_MODEL_VERSION = '0.1.0'


def register_fake_models(test, models):
    """Register `models` ({name: adapter class or (adapter class, antibiotics)}) until `test` ends.

    They are also described in the registry graph the discovery of the prediction page reads, as
    models for any organism that consume the genes of a sample. Everything is restored afterwards,
    so the fakes do not leak into other tests.
    """
    backups = [dict(registry) for registry in _REGISTRIES]

    def restore():
        for registry, backup in zip(_REGISTRIES, backups):
            registry.clear()
            registry.update(backup)
    test.addCleanup(restore)

    graph = services.registry_graph() + _describe(models)  # a copy, with the fakes
    patcher = mock.patch.object(services, 'registry_graph', return_value=graph)
    patcher.start()
    test.addCleanup(patcher.stop)

    for name, model in models.items():
        cls, antibiotics = model if isinstance(model, tuple) else (model, [])
        MODEL_REGISTRY[name] = cls
        MODEL_ANTIBIOTICS[name] = list(antibiotics)
        MODEL_PORTS[name] = FAKE_MODEL_PORTS
        MODEL_VERSIONS[name] = FAKE_MODEL_VERSION


def _describe(models):
    """RDF of fake models: what a minimal descriptor of each would say."""
    graph = Graph()
    (genes,), _ = FAKE_MODEL_PORTS
    for name in models:
        model = model_iri(name)
        parameter = URIRef(f'{model}#genes')
        graph.add((model, RDF.type, SCHEMA.SoftwareApplication))
        graph.add((model, SCHEMA.identifier, Literal(name)))
        graph.add((model, SCHEMA.featureList, EDAM.operation_3482))
        graph.add((model, SCHEMA.taxonomicRange, OBO.NCBITaxon_2))
        graph.add((model, BSC.input, parameter))
        graph.add((parameter, RDF.type, BIOSCHEMAS.FormalParameter))
        graph.add((parameter, SCHEMA.name, Literal(genes.role)))
        graph.add((parameter, SCHEMA.additionalType, data_term(genes.kind)))
        if format_term(genes.kind, genes.format) is not None:
            graph.add((parameter, SCHEMA.encodingFormat, format_term(genes.kind, genes.format)))
    return graph
