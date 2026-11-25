"""Signal handlers for users."""

from django.core.files.storage import default_storage
from django.db import transaction

from .models import User


def delete_avatar_file(instance: User, **_signal_args: object) -> None:
    """When a user is deleted, delete their profile photo file too.

    Connected to post_delete (see AccountsConfig.ready), so it also runs for
    bulk deletes, e.g. the admin's "delete selected users" action. The file is
    removed only once the deletion is committed, so a rolled-back deletion
    keeps the user's photo.
    """
    name = instance.avatar.name
    if name:
        transaction.on_commit(lambda: default_storage.delete(name))
