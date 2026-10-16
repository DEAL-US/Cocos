from django.apps import AppConfig


class SemanticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'semantics'

    def ready(self):
        from . import checks  # noqa: F401 (registers the system checks)
