from typing import final, override

from django.apps import AppConfig
from django.db.models.signals import post_delete


@final
class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    @override
    def ready(self) -> None:
        from .models import User
        from .signals import delete_avatar_file

        post_delete.connect(
            delete_avatar_file, sender=User, dispatch_uid="accounts.delete_avatar_file"
        )
