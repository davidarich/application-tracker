from typing import final, override

from django.apps import AppConfig
from django.db.models.signals import post_delete


@final
class TrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracker"

    @override
    def ready(self) -> None:
        from .models import Resume
        from .signals import delete_resume_file

        post_delete.connect(
            delete_resume_file, sender=Resume, dispatch_uid="tracker.delete_resume_file"
        )
