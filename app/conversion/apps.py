from django.apps import AppConfig
from django.conf import settings


class ConversionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'conversion'

    def ready(self):
        from . import steps

        # In DEBUG purge Celery queues and related Redis keys to keep
        # development runs clean (originally in converter.apps)
        if settings.DEBUG:
            try:
                import redis
                from celery import current_app

                # Purge Celery queues in development
                current_app.control.purge()

                # Connect to Redis and clear celery keys
                r = redis.from_url(settings.CELERY_BROKER_URL)
                for key in r.scan_iter("celery*"):
                    r.delete(key)
                for key in r.scan_iter("celery-task-meta*"):
                    r.delete(key)
            except Exception:
                pass
