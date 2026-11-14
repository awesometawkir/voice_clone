import os
import sys

from django.apps import AppConfig


class VoiceCloneConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'voice_clone'

    def ready(self):
        from .services import pipeline  # noqa: F401  registers job handlers

        serving = 'runserver' in sys.argv and (os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv)
        if serving:
            from .services import jobs
            try:
                jobs.recover()
            except Exception:
                pass  # database not migrated yet
