from django.contrib.humanize.templatetags.humanize import naturaltime

from core.models import TaskStatus

STATUS_BADGE_CLASSES = {
    TaskStatus.PENDING: 'badge-soft badge-warning',
    TaskStatus.RUNNING: 'badge-soft badge-info',
    TaskStatus.COMPLETED: 'badge-soft badge-success',
    TaskStatus.FAILED: 'badge-soft badge-error',
}

def format_process_label(task):
    """Format a user-friendly label with process name and relative time."""
    label = task.process.name if task and task.process else "Unnamed Process"
    timestamp = (task.updated_at or task.created_at) if task else None
    if timestamp:
        label = f"{label} · {naturaltime(timestamp)}"
    return label


def status_badge_class(status):
    return STATUS_BADGE_CLASSES.get(status, 'badge-soft badge-neutral')


def build_process_steps(assembly_status=None, annotation_status=None, json_status=None, is_auto_annotated=False):
    """Progress steps of a process row, from the statuses shown for its assembly, annotation or JSON task."""
    if assembly_status is not None:
        if is_auto_annotated:
            return [
                {
                    "label": "Started",
                    "state": "complete",
                },
                {
                    "label": "Assembled",
                    "state": "complete" if assembly_status in (TaskStatus.RUNNING, TaskStatus.COMPLETED) else "current",
                },
                {
                    "label": "Annotated",
                    "state": _step_state(assembly_status),
                },
            ]

        steps = [
            {
                "label": "Started",
                "state": "complete",
            },
            {
                "label": "Assembled",
                "state": _step_state(assembly_status),
            },
        ]

        steps.append(
                {
                    "label": "Annotated",
                    "state": _step_state(annotation_status) if annotation_status is not None else "pending",
                }
            )

        return steps

    if annotation_status is not None:
        return [
            {
                "label": "Started",
                "state": "complete",
            },
            {
                "label": "Annotating",
                "state": _step_state(annotation_status),
            },
            {
                "label": "Parsed",
                "state": _step_state(annotation_status),
            },
        ]

    if json_status is not None:
        return [
            {
                "label": "Started",
                "state": "complete",
            },
            {
                "label": "Parsed",
                "state": _step_state(json_status),
            },
        ]

    return []

def _step_state(status):
    if status == TaskStatus.COMPLETED:
        return "complete"

    if status == TaskStatus.FAILED:
        return "error"

    return "current"
