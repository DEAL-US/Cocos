"""Base for steps that run as jobs in the bio service."""
from core.steps import Busy, ExternalStep, Started

from . import client

# Statuses the bio service answers when it accepts a job; anything else (e.g. 'busy') means try later.
ACCEPTED_STATUSES = {'pending', 'running', 'annotation_pending'}


def submission_result(response):
    """Started with the job id if the bio service accepted the job, Busy otherwise."""
    if response.get('status') in ACCEPTED_STATUSES and response.get('job_id'):
        return Started(response['job_id'])
    return Busy()


class BioServiceStep(ExternalStep):
    """A step run as a job in the bio service."""

    def job_status(self, job_id):
        return client.get_job_status(job_id)

    def already_saved(self, task, role):
        # collect() may be retried after a partial failure: keep what was already stored.
        return task.task_outputs.filter(role=role).exists()
