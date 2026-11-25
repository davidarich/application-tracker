"""The dashboard page: access, the chart, the job table and its paging."""

from typing import override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .helpers import (
    Status,
    make_application,
    make_job_with_status,
    owner,
)


class DashboardTests(TestCase):
    def test_dashboard_requires_login(self):
        url = reverse("tracker:dashboard")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('tracker:login')}?next={url}")

    def test_dashboard_renders_for_logged_in_user(self):
        user = User.objects.create_user("bob@example.com", "x")
        self.client.force_login(user)
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("tracker/dashboard.html", [t.name for t in response.templates])

    def test_root_redirects_to_dashboard(self):
        response = self.client.get("/")
        self.assertRedirects(
            response, reverse("tracker:dashboard"), fetch_redirect_response=False
        )


class DashboardChartTests(TestCase):
    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def test_shows_chart_with_data(self):
        _ = make_application(timezone.now())
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(response, "Applications by status")
        self.assertContains(response, 'id="status-chart-data"')
        self.assertContains(response, "data-status-chart")

    def test_shows_empty_state_without_data(self):
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(response, "No open applications in the last 14 days")
        self.assertNotContains(response, "data-status-chart")

    def test_chart_legend_and_table_leave_out_closed(self):
        _ = make_application(timezone.now(), Status.APPLIED)
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(response, "Closed and ignored jobs aren't shown.")
        chart_html = response.content.decode().split(
            'aria-labelledby="status-chart-title"'
        )[1]
        chart_html = chart_html.split("</section>")[0]
        self.assertIn("Interviewing", chart_html)
        self.assertNotIn("Closed</", chart_html)
        self.assertNotIn("Ignored</", chart_html)


class DashboardContentTests(TestCase):
    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def test_shows_the_chart_without_the_job_table_or_extra_buttons(self):
        _ = make_job_with_status("Backend", "Acme", Status.APPLIED, timezone.now())
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(response, "data-status-chart")
        self.assertNotContains(response, "data-job-filters")
        self.assertNotContains(response, 'id="jobs"')
        self.assertNotContains(response, "View jobs")
