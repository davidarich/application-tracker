"""The Jobs page's kanban view: a column per open status, with status dropdowns."""

from collections.abc import Sequence
from datetime import timedelta
from typing import cast, override

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from ..jobs import KanbanColumn
from ..models import Application, ApplicationStatusChange, Company, Job
from .helpers import Status, current_jobs_view, make_job_with_status, owner

BOARD = f"{reverse('tracker:jobs')}?view=kanban"


class KanbanBoardTests(TestCase):
    @classmethod
    @override
    def setUpTestData(cls) -> None:
        now = timezone.now()
        _ = make_job_with_status("Not Yet", "Acme", None, now)
        _ = make_job_with_status("Sent", "Acme", Status.APPLIED, now)
        _ = make_job_with_status("Talking", "Globex", Status.INTERVIEWING, now)
        _ = make_job_with_status("Got One", "Globex", Status.OFFER, now)
        _ = make_job_with_status("Over", "Acme", Status.CLOSED, now)
        _ = make_job_with_status("Skipped", "Acme", Status.IGNORED, now)

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def columns(self, **params: str) -> Sequence[KanbanColumn]:
        response = self.client.get(
            reverse("tracker:jobs"), {"view": "kanban", **params}
        )
        return cast(Sequence[KanbanColumn], response.context["columns"])

    def test_toggle_marks_the_current_view(self):
        table = self.client.get(reverse("tracker:jobs")).content.decode()
        self.assertEqual(current_jobs_view(table), ["Table"])
        self.assertIn("view=kanban", table)
        board = self.client.get(BOARD).content.decode()
        self.assertEqual(current_jobs_view(board), ["Kanban"])

    def test_columns_are_the_open_statuses_with_their_jobs(self):
        columns = self.columns()
        self.assertEqual(
            [column.label for column in columns],
            ["Not applied", "Applied", "Responded", "Interviewing", "Offer"],
        )
        by_label = {
            column.label: [job.title for job in column.jobs] for column in columns
        }
        self.assertEqual(by_label["Not applied"], ["Not Yet"])
        self.assertEqual(by_label["Applied"], ["Sent"])
        self.assertEqual(by_label["Responded"], [])
        self.assertEqual(by_label["Interviewing"], ["Talking"])
        self.assertEqual(by_label["Offer"], ["Got One"])

    def test_closed_and_ignored_jobs_are_not_on_the_board(self):
        page = self.client.get(BOARD).content.decode()
        self.assertNotIn(">Over<", page)
        self.assertNotIn(">Skipped<", page)

    def test_search_and_company_filters_apply_but_not_the_status_filter(self):
        titles = [
            job.title for column in self.columns(q="globex") for job in column.jobs
        ]
        self.assertEqual(sorted(titles), ["Got One", "Talking"])
        page = self.client.get(BOARD).content.decode()
        self.assertNotIn('id="job-status"', page)
        self.assertIn('name="view" value="kanban"', page)

    def test_cards_show_title_company_and_a_status_dropdown(self):
        page = self.client.get(BOARD).content.decode()
        job = Job.objects.get(title="Talking")
        card = page[page.index(f'id="job-{job.id}"') :][:4000]
        self.assertIn(reverse("tracker:job_detail", args=[job.id]), card)
        self.assertIn("Globex", card)
        self.assertIn(
            '<option value="interviewing" selected>Interviewing</option>', card
        )
        self.assertIn('<option value="closed">Closed</option>', card)
        self.assertIn("data-autosubmit", card)

    def test_not_applied_cards_offer_not_applied_as_the_current_choice(self):
        page = self.client.get(BOARD).content.decode()
        job = Job.objects.get(title="Not Yet")
        card = page[page.index(f'id="job-{job.id}"') :][:4000]
        self.assertIn('<option value="" selected>Not applied</option>', card)


class KanbanStatusChangeTests(TestCase):
    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def move(self, job: Job, status: str, next_url: str = BOARD) -> str:
        response = self.client.post(
            reverse("tracker:job_status", args=[job.id]),
            {"status": status, "next": next_url},
            follow=True,
        )
        return response.content.decode()

    def test_moving_a_not_applied_job_creates_its_first_application(self):
        job = make_job_with_status("Not Yet", "Acme", None, timezone.now())
        page = self.move(job, Status.APPLIED)
        self.assertIn("Moved Not Yet to Applied.", page)
        application = Application.objects.get(job=job)
        self.assertEqual(application.status, Status.APPLIED)
        self.assertEqual(
            list(
                ApplicationStatusChange.objects.filter(
                    application=application
                ).values_list("status", flat=True)
            ),
            [Status.APPLIED],
        )

    def test_moving_updates_the_latest_application_and_records_history(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        _ = self.move(job, Status.INTERVIEWING)
        application = Application.objects.get(job=job)
        self.assertEqual(application.status, Status.INTERVIEWING)
        statuses = ApplicationStatusChange.objects.filter(
            application=application
        ).values_list("status", flat=True)
        self.assertIn(Status.INTERVIEWING, list(statuses))

    def test_moving_to_closed_says_it_leaves_the_board(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        page = self.move(job, Status.CLOSED)
        self.assertIn(
            "Moved Sent to Closed. Closed jobs aren&#x27;t shown on the board.", page
        )

    def test_redirects_back_to_the_board_at_the_card(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        response = self.client.post(
            reverse("tracker:job_status", args=[job.id]),
            {"status": Status.OFFER, "next": f"{BOARD}&q=sent"},
        )
        self.assertRedirects(
            response, f"{BOARD}&q=sent#job-{job.id}", fetch_redirect_response=False
        )

    def test_ignores_an_off_site_next_address(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        response = self.client.post(
            reverse("tracker:job_status", args=[job.id]),
            {"status": Status.OFFER, "next": "https://evil.example/phish"},
        )
        self.assertRedirects(
            response, f"{BOARD}#job-{job.id}", fetch_redirect_response=False
        )

    def test_choosing_the_current_status_changes_nothing(self):
        job = make_job_with_status("Not Yet", "Acme", None, timezone.now())
        page = self.move(job, "")
        self.assertNotIn("Moved", page)
        self.assertFalse(Application.objects.filter(job=job).exists())

    def test_rejects_an_unknown_status(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        page = self.move(job, "hired")
        self.assertIn("Choose one of the listed statuses.", page)
        self.assertEqual(Application.objects.get(job=job).status, Status.APPLIED)

    def test_another_users_or_a_deleted_job_is_a_404(self):
        other = User.objects.create_user("bob@example.com", "x")
        theirs = Job.objects.create(
            company=Company.objects.create(user_owner=other, name="Initech"),
            title="Theirs",
        )
        deleted = make_job_with_status("Gone", "Acme", Status.APPLIED, timezone.now())
        deleted.is_deleted = True
        deleted.save()
        for job in (theirs, deleted):
            with self.subTest(job.title):
                response = self.client.post(
                    reverse("tracker:job_status", args=[job.id]),
                    {"status": Status.OFFER},
                )
                self.assertEqual(response.status_code, 404)
        self.assertFalse(Application.objects.filter(job=theirs).exists())

    def test_requires_post(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        response = self.client.get(reverse("tracker:job_status", args=[job.id]))
        self.assertEqual(response.status_code, 405)


class KanbanDragAndDropMarkupTests(TestCase):
    """The board markup kanban-dnd.js relies on (its behaviour is browser-side)."""

    def test_board_columns_and_cards_are_marked_for_drag_and_drop(self):
        now = timezone.now()
        not_yet = make_job_with_status("Not Yet", "Acme", None, now)
        sent = make_job_with_status("Sent", "Acme", Status.APPLIED, now)
        self.client.force_login(owner())
        page = self.client.get(BOARD).content.decode()
        self.assertIn("data-kanban>", page)
        self.assertIn("js/kanban-dnd.js", page)
        # Columns carry their status; "Not applied" is "" (never a drop target).
        for status in ("", "applied", "responded", "interviewing", "offer"):
            self.assertIn(f'data-kanban-column data-status="{status}"', page)
        for job in (not_yet, sent):
            card = page[page.index(f'id="job-{job.id}"') :][:1500]
            tag = card[: card.index(">")]
            self.assertIn("data-kanban-card", tag)
            self.assertNotIn("draggable", tag)  # only the handle starts a drag
            self.assertNotIn("cursor-grab", tag)
            handle_at = card.index("data-kanban-handle")
            handle = card[card.rindex("<span", 0, handle_at) : handle_at]
            self.assertIn('draggable="true"', handle)
            self.assertIn('aria-hidden="true"', handle)


class KanbanUndoMoveTests(TestCase):
    """Undoing a status move from the "Moved …" message."""

    @override
    def setUp(self) -> None:
        self.client.force_login(owner())

    def move(self, job: Job, status: str) -> str:
        response = self.client.post(
            reverse("tracker:job_status", args=[job.id]),
            {"status": status, "next": BOARD},
            follow=True,
        )
        return response.content.decode()

    def undo(self) -> str:
        return self.client.post(
            reverse("tracker:undo_status"), follow=True
        ).content.decode()

    def history(self, job: Job) -> list[str]:
        return list(
            ApplicationStatusChange.objects.filter(application__job=job)
            .order_by("changed_at")
            .values_list("status", flat=True)
        )

    def test_moved_message_offers_undo(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        page = self.move(job, Status.OFFER)
        self.assertIn("Moved Sent to Offer.", page)
        self.assertIn(f'action="{reverse("tracker:undo_status")}"', page)

    def test_undo_restores_the_status_time_and_history(self):
        earlier = timezone.now() - timedelta(days=3)
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, earlier)
        history_before = self.history(job)
        _ = self.move(job, Status.INTERVIEWING)
        page = self.undo()
        self.assertIn("Moved Sent back to Applied.", page)
        application = Application.objects.get(job=job)
        self.assertEqual(application.status, Status.APPLIED)
        self.assertEqual(application.updated_at, earlier)
        self.assertEqual(self.history(job), history_before)  # no trace of the move

    def test_undoing_a_move_out_of_not_applied_removes_the_application(self):
        job = make_job_with_status("Not Yet", "Acme", None, timezone.now())
        _ = self.move(job, Status.APPLIED)
        page = self.undo()
        self.assertIn("Moved Not Yet back to Not applied.", page)
        self.assertFalse(Application.objects.filter(job=job).exists())

    def test_undo_returns_to_the_board_at_the_card(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        _ = self.move(job, Status.OFFER)
        response = self.client.post(reverse("tracker:undo_status"))
        self.assertRedirects(
            response, f"{BOARD}#job-{job.id}", fetch_redirect_response=False
        )

    def test_undo_works_once_and_only_for_the_latest_move(self):
        first = make_job_with_status("First", "Acme", Status.APPLIED, timezone.now())
        second = make_job_with_status("Second", "Acme", Status.APPLIED, timezone.now())
        _ = self.move(first, Status.OFFER)
        page = self.move(second, Status.RESPONDED)
        self.assertEqual(page.count(f'action="{reverse("tracker:undo_status")}"'), 1)
        _ = self.undo()
        self.assertEqual(
            Application.objects.get(job=first).status, Status.OFFER
        )  # kept
        self.assertEqual(Application.objects.get(job=second).status, Status.APPLIED)
        self.assertIn("There&#x27;s nothing to undo.", self.undo())

    def test_refuses_when_the_status_changed_since(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        _ = self.move(job, Status.OFFER)
        application = Application.objects.get(job=job)
        application.status = Status.CLOSED  # e.g. changed in another tab
        application.save()
        page = self.undo()
        self.assertIn(
            "Couldn&#x27;t undo the move of Sent: its status has changed since.", page
        )
        self.assertEqual(Application.objects.get(job=job).status, Status.CLOSED)

    def test_another_users_session_cannot_undo(self):
        job = make_job_with_status("Sent", "Acme", Status.APPLIED, timezone.now())
        _ = self.move(job, Status.OFFER)
        self.client.force_login(User.objects.create_user("bob@example.com", "x"))
        self.assertIn("nothing to undo", self.undo())
        self.assertEqual(Application.objects.get(job=job).status, Status.OFFER)

    def test_requires_post_and_login(self):
        url = reverse("tracker:undo_status")
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertRedirects(
            self.client.post(url), f"{reverse('tracker:login')}?next={url}"
        )
