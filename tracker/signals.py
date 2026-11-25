"""Signal handlers for tracker models."""

from django.core.files.storage import default_storage
from django.db import transaction

from .models import Resume


def delete_resume_file(instance: Resume, **_signal_args: object) -> None:
    """When a resume is deleted (with its user), delete its uploaded PDF too.

    Connected to post_delete (see TrackerConfig.ready), which also runs for
    cascades and bulk deletes. The file is removed only once the deletion is
    committed, so a rolled-back deletion keeps it.
    """
    name = instance.file.name
    if name:
        transaction.on_commit(lambda: default_storage.delete(name))
