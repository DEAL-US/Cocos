"""Base for steps that run as jobs in the bio service."""
import logging

import requests
from django.core.cache import cache

from core.steps import Busy, ExternalStep, Started

from . import client

logger = logging.getLogger(__name__)

# Statuses the bio service answers when it accepts a job; anything else (e.g. 'busy') means try later.
ACCEPTED_STATUSES = {'pending', 'running', 'annotation_pending'}

# What the bio service has installed changes only when it is redeployed; a failure to ask is kept
# for less time, so that pages do not wait for it on every load but notice soon when it is back.
TOOLS_CACHE_KEY = 'bioservice:tools'
TOOLS_CACHE_SECONDS = 10 * 60
TOOLS_FAILURE_CACHE_SECONDS = 60


def submission_result(response):
    """Started with the job id if the bio service accepted the job, Busy otherwise."""
    if response.get('status') in ACCEPTED_STATUSES and response.get('job_id'):
        return Started(response['job_id'])
    return Busy()


def installed_tools():
    """What the bio service has installed (GET /tools), or None if it does not answer. Cached."""
    tools = cache.get(TOOLS_CACHE_KEY)
    if tools is None:
        try:
            tools = client.get_tools()
        except (requests.RequestException, ValueError):
            logger.warning('The bio service did not say which tools it has installed')
            tools = {}
        cache.set(TOOLS_CACHE_KEY, tools, TOOLS_CACHE_SECONDS if tools else TOOLS_FAILURE_CACHE_SECONDS)
    return tools or None


class BioServiceStep(ExternalStep):
    """A step run as a job in the bio service."""

    def job_status(self, job_id):
        return client.get_job_status(job_id)

    def job_failure(self, job_id):
        try:
            return client.get_job_failure(job_id)
        except (requests.RequestException, ValueError):
            logger.warning('The bio service did not say why job %s failed', job_id)
            return super().job_failure(job_id)

    def software(self, task):
        # Asked once, when the task finishes: what the job used, as the bio service recorded it.
        return client.get_job_software(task.external_job_id) if task.external_job_id else []

    def expected_software(self):
        tools = installed_tools()
        try:
            return None if tools is None else self.software_of(tools)
        except (KeyError, TypeError):
            logger.warning('The bio service answered GET /tools without what %s uses', self.key)
            return None

    def software_of(self, tools):
        """What a job of this step uses, out of the installed `tools` (the answer of GET /tools)."""
        return []

    def already_saved(self, task, role):
        # collect() may be retried after a partial failure: keep what was already stored.
        return task.task_outputs.filter(role=role).exists()
