"""System checks: plug-ins that were not registered because of their descriptor or the files it
declares, and mistakes in the trust rules."""
from django.core.checks import Error, Warning, register

from .registry.plugins import REJECTED_PLUGINS
from .trust import RulesError, load_rules


@register()
def check_rejected_plugins(app_configs, **kwargs):
    return [
        Warning(f'The {kind} {name} was not registered: {reason}', id='semantics.W001')
        for (kind, name), reason in sorted(REJECTED_PLUGINS.items())
    ]


@register()
def check_trust_rules(app_configs, **kwargs):
    try:
        load_rules()
    except RulesError as error:
        return [Error(f'The trust rules have mistakes: {error}', id='semantics.E001')]
    return []
