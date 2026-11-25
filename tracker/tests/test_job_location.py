"""Job location and workplace type."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from ..models import Company, Job
from .helpers import (
    owner,
)


class JobLocationTests(TestCase):
    def test_location_joins_city_and_state(self):
        company = Company.objects.create(user_owner=owner(), name="Acme")
        self.assertEqual(
            Job(company=company, location_city="Seattle", location_state="WA").location,
            "Seattle, WA",
        )
        self.assertEqual(
            Job(company=company, location_state="Germany").location, "Germany"
        )
        self.assertEqual(Job(company=company).location, "")

    @override_settings(DEBUG=True)
    def test_seed_data_uses_valid_workplace_types(self):
        _ = call_command(
            "seed",
            "--user",
            owner().email,
            "--jobs",
            "60",
            "--seed",
            "3",
            stdout=StringIO(),
        )
        workplace_types = set(Job.objects.values_list("workplace_type", flat=True))
        self.assertLessEqual(workplace_types, {"", *Job.WorkplaceType.values})
        self.assertIn(Job.WorkplaceType.REMOTE.value, workplace_types)
        self.assertTrue(
            Job.objects.filter(workplace_type="remote", location_city="").exists()
        )

    def test_admin_job_list_shows_location_and_workplace(self):
        admin_user = User.objects.create_superuser("admin@example.com", "x")
        self.client.force_login(admin_user)
        _ = Job.objects.create(
            company=Company.objects.create(user_owner=owner(), name="Acme"),
            title="Engineer",
            location_city="Austin",
            location_state="TX",
            workplace_type=Job.WorkplaceType.HYBRID,
        )
        response = self.client.get(reverse("admin:tracker_job_changelist"))
        self.assertContains(response, "Austin, TX")
        self.assertContains(response, "Hybrid")
