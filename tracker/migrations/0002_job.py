import uuid

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0001_company"),
    ]

    operations = [
        migrations.CreateModel(
            name="Skill",
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
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "creation_source",
                    models.CharField(
                        choices=[("manual", "Manual"), ("api", "API")],
                        default="manual",
                        editable=False,
                        help_text="How the record was created. Set by the app, not by users.",
                        max_length=10,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        condition=models.Q(("is_deleted", False)),
                        name="tracker_skill_name_ci_unique",
                        violation_error_message="A skill with this name already exists.",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Job",
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
                ("title", models.CharField(max_length=200)),
                ("posting_url", models.URLField(blank=True)),
                (
                    "location_city",
                    models.CharField(blank=True, max_length=100, verbose_name="city"),
                ),
                (
                    "location_state",
                    models.CharField(
                        blank=True,
                        help_text="State, province or country, e.g. WA, Ontario or Germany.",
                        max_length=100,
                        verbose_name="state / region",
                    ),
                ),
                (
                    "workplace_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("in_office", "In office"),
                            ("hybrid", "Hybrid"),
                            ("remote", "Remote"),
                        ],
                        help_text="Leave blank if the posting doesn't say.",
                        max_length=20,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("salary_min", models.PositiveIntegerField(blank=True, null=True)),
                ("salary_max", models.PositiveIntegerField(blank=True, null=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("date_added", models.DateTimeField(auto_now_add=True)),
                (
                    "creation_source",
                    models.CharField(
                        choices=[("manual", "Manual"), ("api", "API")],
                        default="manual",
                        editable=False,
                        help_text="How the record was created. Set by the app, not by users.",
                        max_length=10,
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jobs",
                        to="tracker.company",
                    ),
                ),
                (
                    "skills",
                    models.ManyToManyField(
                        blank=True, related_name="jobs", to="tracker.skill"
                    ),
                ),
            ],
            options={
                "ordering": ["-date_added"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("salary_max__isnull", True),
                            ("salary_min__isnull", True),
                            ("salary_min__lte", models.F("salary_max")),
                            _connector="OR",
                        ),
                        name="tracker_job_salary_range_valid",
                        violation_error_message="Minimum salary can't exceed maximum salary.",
                    ),
                ],
            },
        ),
    ]
