"""System checks: plug-ins that were not registered because of their descriptor or weights."""
from django.core.checks import Warning, register

from .registry.plugins import REJECTED_PLUGINS


@register()
def check_rejected_plugins(app_configs, **kwargs):
    return [
        Warning(f'The {kind} {name} was not registered: {reason}', id='semantics.W001')
        for (kind, name), reason in sorted(REJECTED_PLUGINS.items())
    ]
