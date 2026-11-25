"""The `seed` management command."""

import itertools
from datetime import timedelta
from io import StringIO
from typing import override
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User

from ..models import (
    Application,
    ApplicationStatusChange,
    Company,
    Contact,
    CoverLetter,
    Job,
    Skill,
)
from ..ownership import active_skills, companies_for, jobs_for
from ..seeding import (
    COMPANIES,
    DELETED_COMPANY,
    DELETED_COMPANY_JOB_TITLE,
    DELETED_JOB_TITLE,
    DELETED_SKILL,
    SEED_SKILLS,
    SKILL_DEVOPS,
    SKILL_FRAMEWORKS,
    SKILL_GROUPS,
    SKILL_LANGUAGES,
)
from .helpers import (
    Status,
    make_job_with_status,
    owner,
)


def visible_companies() -> QuerySet[Company]:
    """Companies the app shows (not soft-deleted)."""
    return Company.objects.filter(is_deleted=False)


def visible_jobs() -> QuerySet[Job]:
    """Jobs the app shows (neither they nor their company soft-deleted)."""
    return Job.objects.filter(is_deleted=False, company__is_deleted=False)


@override_settings(DEBUG=True)
class SeedCommandTests(TestCase):
    @override
    def setUp(self) -> None:
        _ = owner()  # seed defaults to the only user

    def run_seed(self, *args: str) -> str:
        out = StringIO()
        _ = call_command("seed", *args, stdout=out)
        return out.getvalue()

    def test_creates_the_requested_number_of_jobs(self):
        output = self.run_seed("--jobs", "30", "--seed", "1")
        self.assertEqual(visible_jobs().count(), 30)
        self.assertEqual(visible_companies().count(), len(COMPANIES))
        self.assertTrue(Application.objects.exists())
        self.assertIn("Created 30 jobs", output)

    def test_seed_company_names_are_unique_and_include_agencies(self):
        names = [company.name.lower() for company in COMPANIES]
        self.assertEqual(len(names), 30)
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(sum(company.is_staffing_agency for company in COMPANIES), 5)

    def test_seed_companies_get_their_mission_statements(self):
        _ = self.run_seed("--jobs", "5", "--seed", "1")
        missions = {company.name: company.mission_statement for company in COMPANIES}
        self.assertEqual(len(set(missions.values())), len(missions))  # all different
        for company in visible_companies():
            with self.subTest(company.name):
                self.assertEqual(company.mission_statement, missions[company.name])

    def test_application_history_is_consistent(self):
        _ = self.run_seed("--jobs", "80", "--seed", "2", "--days", "20")
        now = timezone.now()
        allowed_moves = {
            (Status.APPLIED, Status.RESPONDED),
            (Status.RESPONDED, Status.INTERVIEWING),
            (Status.INTERVIEWING, Status.OFFER),
        }
        for application in Application.objects.all():
            history = list(
                ApplicationStatusChange.objects.filter(
                    application=application
                ).order_by("changed_at")
            )
            statuses = [change.status for change in history]
            times = [change.changed_at for change in history]
            if statuses == [Status.IGNORED]:
                # Skipped without applying: a single entry, never later changed.
                self.assertEqual(times[0], application.created_at)
                self.assertLessEqual(times[0], now)
                continue
            self.assertNotIn(Status.IGNORED, statuses)
            self.assertEqual(statuses[0], Status.APPLIED)
            self.assertEqual(times[0], application.created_at)
            self.assertEqual(statuses[-1], application.status)
            self.assertEqual(times[-1], application.updated_at)
            self.assertEqual(times, sorted(times))
            self.assertLessEqual(times[-1], now)
            self.assertGreaterEqual(times[0], now - timedelta(days=20, minutes=1))
            for before, after in itertools.pairwise(statuses):
                self.assertTrue(
                    (before, after) in allowed_moves or after == Status.CLOSED,
                    f"unexpected move {before} -> {after}",
                )

    def test_same_seed_gives_the_same_data(self):
        def snapshot() -> list[tuple[str, str]]:
            return sorted(
                (job.title, job.company.name)
                for job in Job.objects.select_related("company")
            )

        _ = self.run_seed("--jobs", "20", "--seed", "7")
        first = snapshot()
        _ = self.run_seed("--jobs", "20", "--seed", "7", "--clear", "--noinput")
        self.assertEqual(snapshot(), first)

    def test_seeding_twice_adds_jobs_and_reuses_companies(self):
        _ = self.run_seed("--jobs", "10", "--seed", "1")
        _ = self.run_seed("--jobs", "10", "--seed", "2")
        self.assertEqual(visible_jobs().count(), 20)
        self.assertEqual(visible_companies().count(), len(COMPANIES))

    def test_clear_replaces_existing_data(self):
        _ = make_job_with_status("Keep me?", "Old Co", Status.APPLIED, timezone.now())
        _ = self.run_seed("--jobs", "5", "--clear", "--noinput")
        self.assertFalse(Job.objects.filter(title="Keep me?").exists())
        self.assertEqual(visible_jobs().count(), 5)

    def test_clear_asks_for_confirmation(self):
        _ = make_job_with_status("Keep me", "Old Co", Status.APPLIED, timezone.now())
        with (
            patch("builtins.input", return_value="no"),
            self.assertRaises(CommandError),
        ):
            _ = self.run_seed("--jobs", "5", "--clear")
        self.assertTrue(Job.objects.filter(title="Keep me").exists())

    @override_settings(DEBUG=False)
    def test_refuses_without_debug_unless_forced(self):
        with self.assertRaises(CommandError):
            _ = self.run_seed("--jobs", "5")
        self.assertFalse(Job.objects.exists())
        _ = self.run_seed("--jobs", "5", "--force")
        self.assertEqual(visible_jobs().count(), 5)

    def test_rejects_negative_jobs_and_non_positive_days(self):
        with self.assertRaises(CommandError):
            _ = self.run_seed("--jobs", "-1")
        with self.assertRaises(CommandError):
            _ = self.run_seed("--days", "0")

    def test_seeds_some_ignored_jobs_without_cover_letters(self):
        _ = self.run_seed("--jobs", "80", "--seed", "2")
        ignored = Application.objects.filter(
            status=Status.IGNORED, job__is_deleted=False
        )
        self.assertGreater(ignored.count(), 0)
        for application in ignored:
            with self.subTest(application.job.title):
                self.assertEqual(
                    ApplicationStatusChange.objects.filter(
                        application=application
                    ).count(),
                    1,
                )
                self.assertFalse(
                    CoverLetter.objects.filter(application=application).exists()
                )


@override_settings(DEBUG=True)
class SeedSkillsTests(TestCase):
    @override
    def setUp(self) -> None:
        _ = owner()  # seed defaults to the only user

    def run_seed(self, *args: str) -> str:
        out = StringIO()
        _ = call_command("seed", *args, stdout=out)
        return out.getvalue()

    def test_seed_skill_list_covers_each_group_with_unique_names(self):
        self.assertEqual(len(SEED_SKILLS), 40)
        for group, _, _ in SKILL_GROUPS:
            self.assertEqual(len(group), 10)
        names = [skill.name.lower() for skill in SEED_SKILLS]
        self.assertEqual(len(set(names)), len(names))
        self.assertTrue(all(skill.description for skill in SEED_SKILLS))

    def test_creates_the_shared_skills_once(self):
        output = self.run_seed("--jobs", "5", "--seed", "1")
        self.assertIn("40 new shared skills", output)
        self.assertEqual(active_skills().count(), 40)
        self.assertEqual(
            Skill.objects.get(name="Kubernetes").description,
            "Orchestrating and scaling containers across clusters of machines.",
        )
        output = self.run_seed("--jobs", "5", "--seed", "2")
        self.assertIn("0 new shared skills", output)
        self.assertEqual(active_skills().count(), 40)

    def test_reuses_an_existing_skill_with_different_case(self):
        _ = Skill.objects.create(name="python", description="Added by hand.")
        _ = self.run_seed("--jobs", "5", "--seed", "1")
        self.assertEqual(Skill.objects.filter(name__iexact="python").count(), 1)
        self.assertEqual(active_skills().count(), 40)

    def test_each_job_gets_skills_from_each_group(self):
        _ = self.run_seed("--jobs", "30", "--seed", "3")
        groups = {
            "languages": {skill.name for skill in SKILL_LANGUAGES},
            "frameworks": {skill.name for skill in SKILL_FRAMEWORKS},
            "devops": {skill.name for skill in SKILL_DEVOPS},
        }
        for job in visible_jobs().prefetch_related("skills"):
            names = {skill.name for skill in job.skills.all()}
            for group, group_names in groups.items():
                with self.subTest(job=job.title, group=group):
                    self.assertTrue(names & group_names)
            self.assertLessEqual(len(names), 8)

    def test_clear_keeps_the_shared_skills(self):
        _ = self.run_seed("--jobs", "5")
        _ = self.run_seed("--jobs", "5", "--clear", "--noinput")
        self.assertEqual(active_skills().count(), 40)


@override_settings(DEBUG=True)
class SeedSkillBackfillTests(TestCase):
    @override
    def setUp(self) -> None:
        _ = owner()

    def run_seed(self, *args: str) -> str:
        out = StringIO()
        _ = call_command("seed", *args, stdout=out)
        return out.getvalue()

    def test_gives_skills_to_existing_jobs_without_any(self):
        old_job = make_job_with_status(
            "Old Job", "Acme", Status.APPLIED, timezone.now()
        )
        output = self.run_seed("--jobs", "0")
        self.assertIn("Gave skills to 1 existing jobs", output)
        self.assertTrue(old_job.skills.exists())
        self.assertEqual(visible_jobs().count(), 1)  # --jobs 0 adds no jobs

    def test_leaves_jobs_that_already_have_skills_alone(self):
        job = make_job_with_status("Has Skills", "Acme", Status.APPLIED, timezone.now())
        rust = Skill.objects.create(name="Rust")
        job.skills.set([rust])
        output = self.run_seed("--jobs", "0")
        self.assertIn("Gave skills to 0 existing jobs", output)
        self.assertEqual(list(job.skills.all()), [rust])

    def test_only_backfills_the_chosen_users_jobs(self):
        other = User.objects.create_user("bob@example.com", "x")
        other_job = Job.objects.create(
            company=Company.objects.create(user_owner=other, name="Globex"),
            title="Theirs",
        )
        _ = self.run_seed("--user", owner().email, "--jobs", "0")
        self.assertFalse(other_job.skills.exists())


@override_settings(DEBUG=True)
class SeedDeletedSamplesTests(TestCase):
    @override
    def setUp(self) -> None:
        _ = owner()

    def run_seed(self, *args: str) -> str:
        out = StringIO()
        _ = call_command("seed", *args, stdout=out)
        return out.getvalue()

    def test_adds_one_soft_deleted_company_job_and_skill(self):
        output = self.run_seed("--jobs", "5", "--seed", "1")
        self.assertIn("added 3 soft-deleted samples", output)
        company = Company.objects.get(name=DELETED_COMPANY.name)
        self.assertTrue(company.is_deleted)
        # The deleted company's job isn't deleted itself, but is hidden with it.
        hidden_job = Job.objects.get(title=DELETED_COMPANY_JOB_TITLE)
        self.assertFalse(hidden_job.is_deleted)
        self.assertNotIn(hidden_job, jobs_for(owner()))
        self.assertTrue(Job.objects.get(title=DELETED_JOB_TITLE).is_deleted)
        self.assertTrue(Skill.objects.get(name=DELETED_SKILL.name).is_deleted)

    def test_samples_are_hidden_in_the_app(self):
        _ = self.run_seed("--jobs", "5", "--seed", "1")
        user = owner()
        self.assertNotIn(DELETED_COMPANY.name, [c.name for c in companies_for(user)])
        titles = [job.title for job in jobs_for(user)]
        self.assertNotIn(DELETED_JOB_TITLE, titles)
        self.assertNotIn(DELETED_COMPANY_JOB_TITLE, titles)
        self.assertNotIn(DELETED_SKILL.name, [s.name for s in active_skills()])
        # Seeded jobs never get the deleted skill.
        self.assertFalse(Job.objects.filter(skills__name=DELETED_SKILL.name).exists())

    def test_samples_are_added_only_once(self):
        _ = self.run_seed("--jobs", "5", "--seed", "1")
        output = self.run_seed("--jobs", "5", "--seed", "2")
        self.assertIn("added 0 soft-deleted samples", output)
        self.assertEqual(Company.objects.filter(name=DELETED_COMPANY.name).count(), 1)
        self.assertEqual(Job.objects.filter(title=DELETED_JOB_TITLE).count(), 1)

    def test_clear_removes_the_users_deleted_records_too(self):
        _ = self.run_seed("--jobs", "5", "--seed", "1")
        _ = self.run_seed("--jobs", "5", "--clear", "--noinput")
        # Recreated once by the second run, not left over from the first.
        self.assertEqual(Company.objects.filter(name=DELETED_COMPANY.name).count(), 1)
        self.assertEqual(Job.objects.filter(title=DELETED_JOB_TITLE).count(), 1)


@override_settings(DEBUG=True)
class SeedContactsTests(TestCase):
    @override
    def setUp(self) -> None:
        _ = owner()

    def test_every_seed_company_gets_contacts(self):
        _ = call_command("seed", "--jobs", "0", stdout=StringIO())
        self.assertFalse(visible_companies().filter(contacts__isnull=True).exists())

    def test_fills_existing_companies_without_contacts_only(self):
        empty = Company.objects.create(user_owner=owner(), name=COMPANIES[0].name)
        known = Company.objects.create(user_owner=owner(), name=COMPANIES[1].name)
        kept = Contact.objects.create(company=known, name="Pat Kept")
        _ = call_command("seed", "--jobs", "0", stdout=StringIO())
        self.assertIn(Contact.objects.filter(company=empty).count(), (1, 2))
        self.assertEqual(list(Contact.objects.filter(company=known)), [kept])
