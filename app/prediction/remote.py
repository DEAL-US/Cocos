"""Client of the model service, which runs the models whose descriptor says they run in a service.

The service has the same kind of jobs as the bio service (status, message, error_kind, software)
and gives the results of a job as a list of {about: ARO term, call, score, evidence} (see the
model-service of Cocos-deployment). The descriptor of each model says where its jobs are sent: a
URL relative to MODEL_SERVICE_BASE, or an absolute one for a model with its own service.
"""
import logging
import os
from urllib.parse import urljoin, urlparse

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

BASE = os.getenv('MODEL_SERVICE_BASE', 'http://localhost:8002')

# What the service has installed changes only when it is redeployed (as for the bio service)
MODELS_CACHE_KEY = 'modelservice:models'
MODELS_CACHE_SECONDS = 10 * 60
MODELS_FAILURE_CACHE_SECONDS = 60


def _url(endpoint, path):
    """The URL of `path` in the service of `endpoint`: MODEL_SERVICE_BASE for a relative endpoint,
    the root of its own service for an absolute one."""
    base = BASE.rstrip('/') + '/' if not urlparse(endpoint).scheme else urljoin(endpoint, '/')
    return urljoin(base, path)


def submit(endpoint, files, organism=None):
    """Send a job to `endpoint` (the urlTemplate of a model) with `files` ({role: (name, content)})
    and, if known, the organism of the sample. Return the job id, or None if the service is busy."""
    data = {'organism': organism} if organism else {}
    response = requests.post(_url(endpoint, endpoint), files=files, data=data, timeout=120)
    if response.status_code == 503:
        return None
    response.raise_for_status()
    return response.json()['job_id']


def get_job(endpoint, job_id):
    """The job as the service of `endpoint` reports it, or None if it does not know it."""
    response = requests.get(_url(endpoint, f'jobs/{job_id}'), timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def get_result(endpoint, job_id):
    """The results of a completed job: [{about, call, score, evidence}, ...]."""
    response = requests.get(_url(endpoint, f'jobs/{job_id}/result'), timeout=30)
    response.raise_for_status()
    return response.json()['results']


def get_raw_output(endpoint, job_id):
    """(file name, content) of the output of the tool itself, or None if it keeps none."""
    response = requests.get(_url(endpoint, f'jobs/{job_id}/raw'), timeout=120)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    disposition = response.headers.get('content-disposition', '')
    name = disposition.split('filename=')[-1].strip('"') if 'filename=' in disposition else 'output'
    return name, response.content


def installed_models(endpoint):
    """What the service of `endpoint` has installed (GET /models), or None if it does not answer. Cached."""
    key = f'{MODELS_CACHE_KEY}:{_url(endpoint, "models")}'
    models = cache.get(key)
    if models is None:
        try:
            response = requests.get(_url(endpoint, 'models'), timeout=5)
            response.raise_for_status()
            models = response.json()
        except (requests.RequestException, ValueError):
            logger.warning('The model service did not say which models it has installed')
            models = {}
        cache.set(key, models, MODELS_CACHE_SECONDS if models else MODELS_FAILURE_CACHE_SECONDS)
    return models or None
