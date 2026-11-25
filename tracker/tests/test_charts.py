"""Counting applications by status and laying out the chart."""

from datetime import timedelta
from typing import cast

from django.test import TestCase

from ..charts import build_status_chart, nice_scale, status_counts
from .helpers import (
    TODAY,
    Status,
    at,
    change_status,
    make_application,
    owner,
)


class StatusCountsTests(TestCase):
    def test_covers_the_last_14_days_ending_today(self):
        data = status_counts(owner(), today=TODAY)
        self.assertEqual(len(data.days), 14)
        self.assertEqual(data.days[-1], TODAY)
        self.assertEqual(data.days[0], TODAY - timedelta(days=13))

    def test_counts_status_held_at_the_end_of_each_day(self):
        application = make_application(at(TODAY - timedelta(days=20)))
        change_status(application, Status.INTERVIEWING, at(TODAY - timedelta(days=5)))

        data = status_counts(owner(), today=TODAY)

        switch = data.days.index(TODAY - timedelta(days=5))
        self.assertEqual(
            data.counts[Status.APPLIED], [1] * switch + [0] * (14 - switch)
        )
        self.assertEqual(
            data.counts[Status.INTERVIEWING], [0] * switch + [1] * (14 - switch)
        )

    def test_applications_count_from_the_day_they_were_created(self):
        _ = make_application(at(TODAY - timedelta(days=2)))
        data = status_counts(owner(), today=TODAY)
        self.assertEqual(data.counts[Status.APPLIED], [0] * 11 + [1] * 3)

    def test_change_at_midnight_counts_on_the_new_day(self):
        _ = make_application(at(TODAY - timedelta(days=1), hour=0))
        data = status_counts(owner(), today=TODAY)
        self.assertEqual(data.counts[Status.APPLIED][-3:], [0, 1, 1])

    def test_future_changes_are_ignored(self):
        application = make_application(at(TODAY - timedelta(days=3)))
        change_status(application, Status.CLOSED, at(TODAY + timedelta(days=1)))
        data = status_counts(owner(), today=TODAY)
        self.assertEqual(data.counts[Status.APPLIED][-1], 1)
        self.assertEqual(data.counts[Status.CLOSED][-1], 0)

    def test_totals_sum_every_status(self):
        _ = make_application(at(TODAY), Status.APPLIED)
        _ = make_application(at(TODAY), Status.OFFER)
        self.assertEqual(status_counts(owner(), today=TODAY).totals[-1], 2)


class StatusChartTests(TestCase):
    def test_nice_scale(self):
        self.assertEqual(nice_scale(0), (4, 1))
        self.assertEqual(nice_scale(3), (3, 1))
        self.assertEqual(nice_scale(7), (8, 2))
        self.assertEqual(nice_scale(23), (30, 10))
        self.assertEqual(nice_scale(100), (100, 50))

    def test_bands_stack_in_status_order_without_closed(self):
        _ = make_application(at(TODAY), Status.APPLIED)
        _ = make_application(at(TODAY), Status.OFFER)
        chart = build_status_chart(status_counts(owner(), today=TODAY))

        self.assertEqual(
            [band.status for band in chart.bands],
            [Status.APPLIED, Status.RESPONDED, Status.INTERVIEWING, Status.OFFER],
        )
        self.assertFalse(chart.is_empty)
        # The top band's line ends at the total (2 of a top of 2: the top edge).
        self.assertTrue(chart.bands[-1].line_path.endswith("1000.0,0.0"))

    def test_closed_applications_do_not_count_towards_the_chart(self):
        _ = make_application(at(TODAY), Status.APPLIED)
        for _ in range(9):
            _ = make_application(at(TODAY), Status.CLOSED)
        chart = build_status_chart(status_counts(owner(), today=TODAY))
        self.assertEqual(chart.top, 1)  # scaled for 1 open application (10 with closed)
        self.assertEqual(chart.rows[-1].total, 1)
        self.assertEqual(len(chart.rows[-1].counts), 4)
        self.assertNotIn(
            "Closed",
            [
                series["label"]
                for series in cast(list[dict[str, str]], chart.to_json()["series"])
            ],
        )

    def test_only_closed_applications_is_empty(self):
        _ = make_application(at(TODAY), Status.CLOSED)
        self.assertTrue(
            build_status_chart(status_counts(owner(), today=TODAY)).is_empty
        )

    def test_today_is_the_rightmost_day(self):
        chart = build_status_chart(status_counts(owner(), today=TODAY))
        self.assertEqual(chart.day_labels[-1].left, 100)
        self.assertTrue(chart.day_labels[-1].is_today)
        self.assertEqual(chart.day_labels[-1].align, "end")

    def test_thin_bands_get_no_direct_label(self):
        for _ in range(20):
            _ = make_application(at(TODAY), Status.APPLIED)
        _ = make_application(at(TODAY), Status.OFFER)
        chart = build_status_chart(status_counts(owner(), today=TODAY))
        labels = {band.status: band.label_top for band in chart.bands}
        self.assertIsNotNone(labels[Status.APPLIED])
        self.assertIsNone(labels[Status.OFFER])

    def test_empty_when_there_are_no_applications(self):
        self.assertTrue(
            build_status_chart(status_counts(owner(), today=TODAY)).is_empty
        )


class IgnoredChartTests(TestCase):
    def test_ignored_jobs_are_not_charted(self):
        _ = make_application(at(TODAY), Status.APPLIED)
        for _ in range(9):
            _ = make_application(at(TODAY), Status.IGNORED)
        chart = build_status_chart(status_counts(owner(), today=TODAY))
        self.assertNotIn(Status.IGNORED, [band.status for band in chart.bands])
        self.assertEqual(
            chart.top, 1
        )  # scaled for 1 open application (10 with ignored)
        self.assertEqual(chart.rows[-1].total, 1)

    def test_only_ignored_jobs_is_empty(self):
        _ = make_application(at(TODAY), Status.IGNORED)
        self.assertTrue(
            build_status_chart(status_counts(owner(), today=TODAY)).is_empty
        )
