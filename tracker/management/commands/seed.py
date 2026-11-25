"""`manage.py seed`: fill the database with realistic mock data for development."""

import random
from argparse import ArgumentTypeError
from typing import cast, final, override

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from accounts.models import User

from ...seeding import clear_tracker_data, seed


def non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise ArgumentTypeError("must be 0 or more")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise ArgumentTypeError("must be at least 1")
    return number


@final
class Command(BaseCommand):
    help = (
        "Add mock companies, contacts, jobs and applications (with status history, "
        "cover letters and shared skills) for development. Refuses to run unless "
        "DEBUG is on."
    )

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        _ = parser.add_argument(
            "--user",
            metavar="EMAIL",
            default=None,
            help="Seed data for this user (optional when there's exactly one user).",
        )
        _ = parser.add_argument(
            "--jobs",
            type=non_negative_int,
            default=60,
            help=(
                "Number of jobs to create (default 60). Use 0 to only add the shared "
                "skills and give skills to existing jobs that have none."
            ),
        )
        _ = parser.add_argument(
            "--days",
            type=positive_int,
            default=30,
            help="Spread activity over this many past days (default 30).",
        )
        _ = parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Random seed, for the same data every run.",
        )
        _ = parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete the user's existing companies, jobs and applications first.",
        )
        _ = parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_false",
            dest="interactive",
            help="Don't ask for confirmation before --clear.",
        )
        _ = parser.add_argument(
            "--force", action="store_true", help="Run even when DEBUG is off."
        )

    @override
    def handle(self, *args: object, **options: object) -> None:
        email, jobs, days = options["user"], options["jobs"], options["days"]
        random_seed = options["seed"]
        clear, interactive, force = (
            options["clear"],
            options["interactive"],
            options["force"],
        )
        assert isinstance(jobs, int) and isinstance(days, int)
        assert random_seed is None or isinstance(random_seed, int)
        assert email is None or isinstance(email, str)

        if not cast(bool, settings.DEBUG) and not force:
            raise CommandError(
                "DEBUG is off, so this may be a production database. "
                + "Use --force if you really want to add mock data here."
            )

        user = self.find_user(email)

        if clear:
            if interactive:
                answer = input(
                    f"This deletes ALL of {user.email}'s companies, contacts, jobs, "
                    + "applications and cover letters. Type 'yes' to continue: "
                )
                if answer.strip().lower() != "yes":
                    raise CommandError("Cancelled; nothing was changed.")
            clear_tracker_data(user)
            self.stdout.write(f"Cleared {user.email}'s existing tracker data.")

        result = seed(user=user, jobs=jobs, days=days, rng=random.Random(random_seed))
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {result.jobs} jobs, {result.applications} applications "
                + f"({result.status_changes} status changes, {result.cover_letters} cover "
                + f"letters), {result.companies} companies and {result.contacts} contacts "
                + f"for {user.email}, and {result.skills} new shared skills. Gave skills "
                + f"to {result.jobs_given_skills} existing jobs that had none, and added "
                + f"{result.deleted_samples} soft-deleted samples (hidden in the app)."
            )
        )

    def find_user(self, email: str | None) -> User:
        """The user named by --user, or the only user when there's just one."""
        if email is not None:
            try:
                return User.objects.get_by_natural_key(email)
            except User.DoesNotExist:
                raise CommandError(
                    f"No user with the email address {email!r}."
                ) from None
        users = list(User.objects.all()[:2])
        if len(users) != 1:
            raise CommandError(
                "There's no user yet; create one with `manage.py createsuperuser`."
                if not users
                else "There are several users; choose one with --user EMAIL."
            )
        return users[0]
