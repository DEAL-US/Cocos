import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class PredictionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'prediction'
    
    def ready(self):
        from . import checks, steps  # noqa: F401 (checks registers the system checks)

        # Import all modules under ai_models (recursively) so that model adapter
        # decorators run. We prefer `app.ai_models` (package under the Django
        # project) and fall back to a top-level `ai_models` package for
        # compatibility.
        try:
            import importlib
            from pathlib import Path

            try:
                import app.ai_models as ai_models_pkg
                prefix = 'app.ai_models'
            except Exception:
                import ai_models as ai_models_pkg
                prefix = 'ai_models'

            base = Path(ai_models_pkg.__file__).resolve().parent
            for py in base.rglob('*.py'):
                if py.name == '__init__.py':
                    continue
                rel = py.relative_to(base)
                parts = list(rel.with_suffix('').parts)
                module_name = prefix + '.' + '.'.join(parts)
                try:
                    importlib.import_module(module_name)
                except Exception:
                    # Don't block startup for import errors in individual model modules, but say why
                    # the model is missing (e.g. no descriptor.ttl).
                    logger.exception('Could not load the model module %s', module_name)
        except Exception:
            pass
