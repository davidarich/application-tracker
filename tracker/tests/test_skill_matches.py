"""The dashboard's best skill matches: unapplied jobs ranked by resume skills."""

from datetime import timedelta
from typing import ClassVar, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..matching import best_skill_matches, resume_skill_ids
from ..models import Company, Job, Skill
from ..ownership import resume_for
from .helpers import Status, make_job_with_status, owner

DASHBOARD = reverse("tracker:dashboard")


class SkillMatchTests(TestCase):
    user: ClassVar[User]
    python: ClassVar[Skill]
    go: ClassVar[Skill]
    docker: ClassVar[Skill]
    rust: ClassVar[Skill]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = owner()
        cls.python = Skill.objects.create(name="Python")
        cls.go = Skill.objects.create(name="Go")
        cls.docker = Skill.objects.create(name="Docker")
        cls.rust = Skill.objects.create(name="Rust")
        resume_for(cls.user).skills.set([cls.python, cls.go, cls.docker])

    def job(
        self, title: str, *skills: Skill, status: str | None = None, days_ago: int = 0
    ) -> Job:
        job = make_job_with_status(
            title, "Acme", status, timezone.now() - timedelta(days=days_ago)
        )
        job.skills.set(skills)
        return job

    def matches(self) -> list[tuple[str, int]]:
        found = best_skill_matches(self.user, resume_skill_ids(self.user))
        return [(match.job.title, match.percent) for match in found]

    def test_ranks_by_the_share_of_the_jobs_skills_on_the_resume(self):
        _ = self.job("Half", self.python, self.rust)
        _ = self.job("All", self.python, self.go)
        _ = self.job("Third", self.go, self.rust, Skill.objects.create(name="Kotlin"))
        self.assertEqual(self.matches(), [("All", 100), ("Half", 50), ("Third", 33)])

    def test_ties_go_to_more_matching_skills_then_newer_jobs(self):
        _ = self.job("One of one", self.python, days_ago=1)
        _ = self.job("Two of two", self.python, self.go, days_ago=5)
        _ = self.job("Newer one of one", self.docker, days_ago=0)
        self.assertEqual(
            [title for title, _ in self.matches()],
            ["Two of two", "Newer one of one", "One of one"],
        )

    def test_only_jobs_not_yet_applied_to(self):
        _ = self.job("Not applied", self.python)
        for status in (
            Status.APPLIED,
            Status.INTERVIEWING,
            Status.CLOSED,
            Status.IGNORED,
        ):
            _ = self.job(f"Status {status}", self.python, status=status)
        self.assertEqual(self.matches(), [("Not applied", 100)])

    def test_leaves_out_deleted_jobs_jobs_without_skills_and_no_match(self):
        deleted = self.job("Deleted", self.python)
        _ = Job.objects.filter(id=deleted.id).update(is_deleted=True)
        gone_company = Company.objects.create(
            user_owner=self.user, name="Gone", is_deleted=True
        )
        Job.objects.create(company=gone_company, title="Deleted company").skills.set(
            [self.python]
        )
        _ = self.job("No skills")
        _ = self.job("No match", self.rust)
        self.assertEqual(self.matches(), [])

    def test_deleted_skills_count_on_neither_side(self):
        retired = Skill.objects.create(name="Perl", is_deleted=True)
        resume_for(self.user).skills.add(retired)
        _ = self.job("Mixed", self.python, retired, self.rust)
        self.assertEqual(self.matches(), [("Mixed", 50)])  # Python of Python, Rust

    def test_shows_matched_and_missing_skills(self):
        _ = self.job("Backend", self.rust, self.go, self.python)
        [match] = best_skill_matches(self.user, resume_skill_ids(self.user))
        self.assertEqual(
            (match.matched, match.missing, match.total), (["Go", "Python"], ["Rust"], 3)
        )

    def test_top_ten_only(self):
        for n in range(12):
            _ = self.job(f"Job {n}", self.python)
        self.assertEqual(len(self.matches()), 10)

    def test_only_the_users_own_jobs(self):
        bob = User.objects.create_user("bob@example.com", "x")
        Job.objects.create(
            company=Company.objects.create(user_owner=bob, name="Bob Co"),
            title="Bob's job",
        ).skills.set([self.python])
        self.assertEqual(self.matches(), [])

    def test_dashboard_lists_the_matches(self):
        self.client.force_login(self.user)
        job = self.job("Platform Engineer", self.python, self.go, self.rust)
        page = self.client.get(DASHBOARD).content.decode()
        section = page[page.index('id="skill-matches"') :]
        self.assertIn(f'href="{reverse("tracker:job_detail", args=[job.id])}"', section)
        self.assertIn("Platform Engineer", section)
        self.assertIn("2 of 3 skills · Missing Rust", section)
        self.assertIn(">67%<", section)
        self.assertIn('style="width: 67%"', section)

    def test_dashboard_empty_states(self):
        self.client.force_login(self.user)
        _ = self.job("No match", self.rust)
        self.assertContains(
            self.client.get(DASHBOARD),
            "None of the jobs you haven't applied to share skills",
        )
        resume_for(self.user).skills.clear()
        page = self.client.get(DASHBOARD).content.decode()
        self.assertIn(f'href="{reverse("tracker:resume")}#skills"', page)
        self.assertIn("to see which jobs match them.", page)
