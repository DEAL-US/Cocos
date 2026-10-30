"""Test helpers: register fake prediction models for the duration of a test, and a fake model service."""
import json
import re
from unittest import mock

import responses
from django.core.cache import cache
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from core.models import File
from core.steps import DataKind, Port
from core.testing import _job_ids, _multipart_parts
from semantics.namespaces import BIOSCHEMAS, BSC, EDAM, OBO, SCHEMA
from semantics.registry.descriptors import model_iri
from semantics.registry.mappings import data_term, format_term

from . import remote, services
from .adapters.registry import (MODEL_ANTIBIOTICS, MODEL_DATA_ORGANISMS, MODEL_ENDPOINTS, MODEL_ORGANISMS, MODEL_PORTS,
                                MODEL_REGISTRY, MODEL_VERSIONS, MODEL_WEIGHTS)

# What the descriptor of a fake model declares: the genes of an annotation in, a CSV out.
FAKE_MODEL_PORTS = ((Port('genes', DataKind.GENE_SET, File.FileType.JSON),),
                    (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),))

_REGISTRIES = (MODEL_REGISTRY, MODEL_ANTIBIOTICS, MODEL_ORGANISMS, MODEL_PORTS, MODEL_VERSIONS, MODEL_DATA_ORGANISMS,
               MODEL_WEIGHTS, MODEL_ENDPOINTS)
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


# --- Models that run in a service

# What the descriptor of a fake remote model declares: an assembly in; a CSV and the output of the tool out.
FAKE_REMOTE_MODEL_PORTS = ((Port('assembly', DataKind.ASSEMBLY, File.FileType.FASTA),),
                           (Port('predictions', DataKind.RESISTANCE_PREDICTION, File.FileType.CSV),
                            Port('tool_output', DataKind.RESISTANCE_PREDICTION, File.FileType.JSON)))


def register_fake_remote_models(test, models):
    """Register models that run in a service ({name: antibiotics}) until `test` ends; their jobs
    are sent to predict/<name> of the model service (see FakeModelService)."""
    register_fake_models(test, {name: (None, antibiotics) for name, antibiotics in models.items()})
    for name in models:
        MODEL_PORTS[name] = FAKE_REMOTE_MODEL_PORTS
        MODEL_ENDPOINTS[name] = f'predict/{name}'


class FakeModelService:
    """In-memory imitation of the model service HTTP API (see the model-service of Cocos-deployment).

    - `results`: {model: results of its jobs, as the service gives them ([{about, call, score, evidence}])}
    - `status_sequence`: statuses returned by successive GET /jobs/<id> calls of each job (the last one repeats)
    - `busy`: answer 503 to every submission
    - `error_kind`: why failed jobs failed
    """
    SOFTWARE = [{'name': 'FakeTool', 'version': '2.0', 'type': 'tool'},
                {'name': 'FakeTool database', 'version': '2026-01', 'type': 'database'}]
    RAW_OUTPUT = b'{"genes": ["blaFAKE-1"]}'

    def __init__(self, results=None, status_sequence=('running', 'completed'), busy=False, error_kind='input'):
        self.results = results or {}
        self.status_sequence = status_sequence
        self.busy = busy
        self.error_kind = error_kind
        self.jobs = {}
        self.submissions = []
        self._mock = responses.RequestsMock(assert_all_requests_are_fired=False)

    def __enter__(self):
        base = re.escape(remote.BASE.rstrip('/'))
        self._mock.start()
        self._mock.add_callback(responses.POST, re.compile(rf'{base}/predict/[^/]+$'), self._submit)
        self._mock.add_callback(responses.GET, re.compile(rf'{base}/jobs/[^/]+$'), self._job)
        self._mock.add_callback(responses.GET, re.compile(rf'{base}/jobs/[^/]+/result$'), self._result)
        self._mock.add(responses.GET, re.compile(rf'{base}/jobs/[^/]+/raw$'), body=self.RAW_OUTPUT,
                       headers={'content-disposition': 'attachment; filename="output.json"'})
        self._mock.add(responses.GET, f'{remote.BASE.rstrip("/")}/models',
                       json={name: {'inputs': ['assembly'], 'software': self.SOFTWARE} for name in self.results})
        cache.clear()  # what the service has installed is asked again, to this fake
        return self

    def __exit__(self, *exc):
        self._mock.stop()
        self._mock.reset()
        cache.clear()

    def _submit(self, request):
        model = request.url.rstrip('/').rsplit('/', 1)[-1]
        self.submissions.append({'model': model, 'parts': _multipart_parts(request)})
        if self.busy:
            return (503, {}, json.dumps({'status': 'busy'}))
        job_id = f'model-job-{next(_job_ids)}'
        self.jobs[job_id] = {'model': model, 'sequence': list(self.status_sequence)}
        return (200, {}, json.dumps({'job_id': job_id, 'status': 'pending'}))

    def _job(self, request):
        job_id = request.url.rstrip('/').rsplit('/', 1)[-1]
        job = self.jobs.get(job_id)
        if job is None:
            return (404, {}, json.dumps({'detail': 'Job not found'}))
        status = job['sequence'].pop(0) if len(job['sequence']) > 1 else job['sequence'][0]
        body = {'job_id': job_id, 'model': job['model'], 'status': status, 'software': self.SOFTWARE}
        if status == 'failed':
            body.update(message='The tool failed on its input', error_kind=self.error_kind)
        return (200, {}, json.dumps(body))

    def _result(self, request):
        job_id = request.url.rstrip('/').split('/')[-2]
        return (200, {}, json.dumps({'model': self.jobs[job_id]['model'],
                                     'results': self.results[self.jobs[job_id]['model']]}))
