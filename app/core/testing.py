"""
Test support: a fake bio service mocked at HTTP level and a mixin for end-to-end flow tests.
"""
import itertools
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import responses
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings

from app.celery import app as celery_app
from bioservice import client as bio_api_client
from bioservice.steps import TOOLS_CACHE_KEY

User = get_user_model()

FIXTURES_DIR = Path(__file__).resolve().parent.parent / 'conversion' / 'tests' / 'fixtures'
BAKTA_JSON = json.loads((FIXTURES_DIR / 'small.json').read_text(encoding='utf-8'))
ASSEMBLY_FASTA = b'>contig_1\nATGCATGCATGC\n'

# What the jobs of the fake service report they used, by technology, like GET /jobs/<id> of the real one
ASSEMBLY_SOFTWARE = {
    'ont': [{'name': 'Raven', 'version': '1.8.3', 'type': 'tool', 'biotools': 'raven'}],
    'illumina': [{'name': 'SPAdes', 'version': '4.3.0', 'type': 'tool', 'biotools': 'spades'}],
}
ANNOTATION_SOFTWARE = [
    {'name': 'Bakta', 'version': '1.12.1', 'type': 'tool', 'biotools': 'bakta'},
    {'name': 'Bakta database', 'version': '6.0', 'type': 'database', 'variant': 'light', 'doi': '10.5281/zenodo.14916843'},
]


# Job ids are unique across every FakeBioService of a test run, like the ids of the real service:
# a task of a later request must not get the id of an earlier one (external_job_id is unique).
_job_ids = itertools.count(1)


class FakeBioService:
    """In-memory imitation of the bio service HTTP API.

    - `start_behavior`: 'ok' accepts new jobs, 'busy' answers 503 to every submission.
    - `status_sequence`: statuses returned by successive GET /jobs/<id> calls for each job;
      the last one is repeated once the sequence is exhausted. When not given, assembly jobs
      end in 'assembled', auto-annotated assemblies and annotations end in 'annotated'.
    - `missing_jobs`: GET /jobs/<id> answers 404.
    - `annotation_payload`: Bakta JSON returned by annotation downloads (defaults to the small fixture).
    """

    def __init__(self, start_behavior='ok', status_sequence=None, missing_jobs=False, annotation_payload=None):
        self.annotation_payload = BAKTA_JSON if annotation_payload is None else annotation_payload
        self.start_behavior = start_behavior
        self.status_sequence = status_sequence
        self.missing_jobs = missing_jobs
        self.jobs = {}
        self.submissions = []
        self._mock = responses.RequestsMock(assert_all_requests_are_fired=False)

    # --- lifecycle
    def __enter__(self):
        self._mock.start()
        base = re.escape(bio_api_client.BASE.rstrip('/'))
        self._mock.add_callback(responses.POST, re.compile(rf'{base}/assembly/(ont|illumina).*'), self._submit_assembly)
        self._mock.add_callback(responses.POST, re.compile(rf'{base}/annotation/bakta/upload.*'), self._submit_annotation)
        self._mock.add_callback(responses.GET, re.compile(rf'{base}/jobs/[^/?]+$'), self._job_status)
        self._mock.add(responses.GET, f'{bio_api_client.BASE.rstrip("/")}/tools',
                       json={'assembly': ASSEMBLY_SOFTWARE, 'annotation': ANNOTATION_SOFTWARE})
        cache.delete(TOOLS_CACHE_KEY)  # what the service has installed is asked again, to this fake
        self._mock.add_callback(responses.GET, re.compile(rf'{base}/assembly/[^/]+/download.*'), self._download_assembly)
        self._mock.add_callback(responses.GET, re.compile(rf'{base}/annotation/[^/]+/download.*'), self._download_annotation)
        return self

    def __exit__(self, *exc):
        self._mock.stop()
        self._mock.reset()
        cache.delete(TOOLS_CACHE_KEY)

    # --- helpers for assertions
    def submissions_to(self, endpoint):
        return [s for s in self.submissions if s['endpoint'] == endpoint]

    # --- callbacks
    def _new_job(self, kind, annotate, software=()):
        job_id = f'job-{next(_job_ids)}'
        if self.status_sequence is not None:
            sequence = list(self.status_sequence)
        elif kind == 'annotation' or annotate:
            sequence = ['running', 'annotated']
        else:
            sequence = ['running', 'assembled']
        self.jobs[job_id] = {'kind': kind, 'annotate': annotate, 'sequence': sequence, 'status': 'pending',
                             'software': list(software)}
        return job_id

    def _busy(self):
        return (503, {}, json.dumps({'status': 'busy', 'detail': 'Server busy'}))

    def _submit_assembly(self, request):
        url = urlparse(request.url)
        endpoint = url.path.rsplit('/', 1)[-1]
        annotate = parse_qs(url.query).get('annotate', ['false'])[0] == 'true'
        self.submissions.append({
            'endpoint': f'assembly/{endpoint}',
            'annotate': annotate,
            'files': _multipart_parts(request),
        })
        if self.start_behavior == 'busy':
            return self._busy()
        job_id = self._new_job('assembly', annotate, ASSEMBLY_SOFTWARE[endpoint] + (ANNOTATION_SOFTWARE if annotate else []))
        return (200, {}, json.dumps({'job_id': job_id, 'status': 'pending'}))

    def _submit_annotation(self, request):
        self.submissions.append({
            'endpoint': 'annotation/upload',
            'annotate': True,
            'threads': parse_qs(urlparse(request.url).query).get('threads', [None])[0],
            'files': _multipart_parts(request),
        })
        if self.start_behavior == 'busy':
            return self._busy()
        job_id = self._new_job('annotation', True, ANNOTATION_SOFTWARE)
        return (200, {}, json.dumps({'job_id': job_id, 'status': 'annotation_pending'}))

    def _job_status(self, request):
        job_id = urlparse(request.url).path.rsplit('/', 1)[-1]
        job = self.jobs.get(job_id)
        if self.missing_jobs or not job:
            return (404, {}, json.dumps({'detail': 'Job not found'}))
        job['status'] = job['sequence'].pop(0) if len(job['sequence']) > 1 else job['sequence'][0]
        return (200, {}, json.dumps({'job_id': job_id, 'status': job['status'], 'software': job['software']}))

    def _download_assembly(self, request):
        job_id = urlparse(request.url).path.split('/')[-2]
        job = self.jobs.get(job_id)
        if not job or job['status'] not in ('assembled', 'annotation_pending', 'annotated'):
            return (400, {}, json.dumps({'detail': 'Assembly not completed'}))
        return (200, {'Content-Type': 'application/octet-stream'}, ASSEMBLY_FASTA)

    def _download_annotation(self, request):
        job_id = urlparse(request.url).path.split('/')[-2]
        job = self.jobs.get(job_id)
        if not job or job['status'] != 'annotated':
            return (400, {}, json.dumps({'detail': 'Annotation not completed'}))
        return (200, {}, json.dumps(self.annotation_payload))


def _multipart_parts(request):
    """Return {field_name: content_bytes} from a multipart request body."""
    body = request.body if isinstance(request.body, bytes) else (request.body or '').encode()
    content_type = request.headers.get('Content-Type', '')
    match = re.search(r'boundary=(.+)', content_type)
    if not match:
        return {}
    boundary = match.group(1).encode()
    parts = {}
    for chunk in body.split(b'--' + boundary):
        if b'\r\n\r\n' not in chunk:
            continue
        headers, content = chunk.split(b'\r\n\r\n', 1)
        name = re.search(rb'name="([^"]+)"', headers)
        if name:
            parts[name.group(1).decode()] = content.removesuffix(b'\r\n')
    return parts


class FlowTestMixin:
    """Run Celery tasks synchronously and store uploads in a temporary MEDIA_ROOT."""

    def setUp(self):
        super().setUp()
        self._media_dir = tempfile.mkdtemp()
        self._media_override = override_settings(MEDIA_ROOT=self._media_dir)
        self._media_override.enable()
        self._eager_backup = (celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates)
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = False

        self.user = User.objects.create_user(username='flow-user', password='pass1234', email='flow@example.com')
        self.other_user = User.objects.create_user(username='other-user', password='pass1234', email='other@example.com')
        self.client.login(username='flow-user', password='pass1234')

    def tearDown(self):
        celery_app.conf.task_always_eager, celery_app.conf.task_eager_propagates = self._eager_backup
        self._media_override.disable()
        shutil.rmtree(self._media_dir, ignore_errors=True)
        super().tearDown()
