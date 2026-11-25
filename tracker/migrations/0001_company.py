import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Company",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "user_owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="companies",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("website", models.URLField(blank=True)),
                ("is_staffing_agency", models.BooleanField(default=False)),
                ("mission_statement", models.TextField(blank=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("date_added", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name_plural": "companies",
                "ordering": ["name"],
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("user_owner"),
                        condition=models.Q(("is_deleted", False)),
                        name="tracker_company_owner_name_ci_unique",
                        violation_error_message="You already have a company with this name.",
                    ),
                ],
            },
        ),
    ]
