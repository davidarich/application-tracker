"""Page size parsing and page number links."""

from django.http import QueryDict
from django.test import TestCase

from ..jobs import JobFilters
from ..paging import page_numbers


class PagingTests(TestCase):
    def test_per_page_defaults_to_25_and_accepts_only_listed_sizes(self):
        self.assertEqual(JobFilters.from_query(QueryDict("")).per_page, 25)
        self.assertEqual(JobFilters.from_query(QueryDict("per_page=50")).per_page, 50)
        self.assertEqual(JobFilters.from_query(QueryDict("per_page=7")).per_page, 25)
        self.assertEqual(JobFilters.from_query(QueryDict("per_page=x")).per_page, 25)

    def test_page_size_is_not_a_filter(self):
        self.assertFalse(JobFilters.from_query(QueryDict("per_page=50")).is_filtered)

    def test_page_numbers(self):
        self.assertEqual(page_numbers(1, 1), [1])
        self.assertEqual(page_numbers(1, 4), [1, 2, 3, 4])
        self.assertEqual(page_numbers(6, 12), [1, None, 5, 6, 7, None, 12])
        self.assertEqual(page_numbers(1, 12), [1, 2, None, 12])
        self.assertEqual(page_numbers(3, 12), [1, 2, 3, 4, None, 12])
