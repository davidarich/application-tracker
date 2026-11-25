"""Posting links are saved without tracking parameters, by the job form, the
API and the admin; anything resembling an ID is kept."""

from typing import ClassVar, override
from urllib.parse import urlencode

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from api.tests.helpers import ApiTestCase, Json, names

from ..models import Company, Job
from ..posting_urls import clean_posting_url, looks_like_id, posting_url_key

TRACKED = (
    "https://jobs.lever.co/acme/abc-123?utm_source=linkedin&utm_medium=social"
    + "&utm_campaign=spring&utm_id=7&gclid=x&fbclid=y&lever-source=LinkedIn"
)
CLEAN = "https://jobs.lever.co/acme/abc-123"


class CleanPostingUrlTests(SimpleTestCase):
    def test_utm_parameters_are_always_removed(self):
        self.assertEqual(
            clean_posting_url(
                "https://acme.com/jobs/1?UTM_Source=x&utm_medium=y&utm_term=z"
                + "&utm_content=a&utm_campaign=b&utm_id=c&utm_source_platform=d"
            ),
            "https://acme.com/jobs/1",
        )

    def test_click_ids_are_removed_even_though_they_end_in_id(self):
        url = "https://acme.com/jobs/1?gclid=a&fbclid=b&msclkid=c&li_fat_id=d&mc_cid=e&mc_eid=f"
        self.assertEqual(clean_posting_url(url), "https://acme.com/jobs/1")

    def test_source_and_referral_parameters_are_removed(self):
        url = (
            "https://acme.com/jobs/1?ref=hn&source=LinkedIn&src=JB&gh_src=abc"
            + "&__jvst=Job+Board&__jvsd=LinkedIn&iis=Job+Board&iisn=x&trk=public"
        )
        self.assertEqual(clean_posting_url(url), "https://acme.com/jobs/1")

    def test_anything_resembling_an_id_is_kept(self):
        kept = [
            "gh_jid=4567",  # Greenhouse on a company site
            "ashby_jid=abc",  # Ashby on a company site
            "jobId=12",
            "job_id=12",
            "currentJobId=12",  # LinkedIn
            "refId=abc",  # LinkedIn: tracking, but it looks like an ID
            "trackingId=def",
            "jk=abc",  # Indeed's job key
            "vjk=def",
            "job=12345",  # Taleo
            "career_job_req_id=88",  # SuccessFactors
            "token=123",  # Greenhouse embeds
            "reqid=9",
            "source_id=3",  # resembles an ID, so not treated as a source
        ]
        url = "https://acme.com/jobs?" + "&".join(kept)
        self.assertEqual(clean_posting_url(url), url)

    def test_other_parameters_are_kept_in_order_exactly_as_written(self):
        url = "https://career5.sapsf.com/career?company=Acme&career_ns=job_listing&lang=en%2DUS&q=a+b"
        self.assertEqual(clean_posting_url(url + "&utm_source=x"), url)
        self.assertEqual(
            clean_posting_url(
                "https://boards.greenhouse.io/embed/job_app?for=acme&token=1&utm_source=x"
            ),
            "https://boards.greenhouse.io/embed/job_app?for=acme&token=1",
        )

    def test_mixed(self):
        self.assertEqual(
            clean_posting_url(
                "https://acme.com/careers?utm_source=x&gh_jid=4567&ref=hn&lang=en"
            ),
            "https://acme.com/careers?gh_jid=4567&lang=en",
        )

    def test_host_is_lowercased_and_the_rest_left_alone(self):
        self.assertEqual(
            clean_posting_url("  HTTPS://Jobs.Lever.CO/Acme/ABC?utm_source=x#Apply  "),
            "https://jobs.lever.co/Acme/ABC#Apply",
        )
        self.assertEqual(
            clean_posting_url("https://acme.com:8443/jobs/1?utm_source=x"),
            "https://acme.com:8443/jobs/1",
        )

    def test_links_without_parameters_and_non_links_are_unchanged(self):
        for value in (
            "https://acme.com/jobs/1",
            "https://acme.com/jobs/1#top",
            "",
            "not a link",
        ):
            self.assertEqual(clean_posting_url(value), value)
        self.assertEqual(
            clean_posting_url("https://acme.com/jobs/1?"), "https://acme.com/jobs/1"
        )
        self.assertEqual(
            clean_posting_url("https://acme.com/jobs/1?&&a=1&"),
            "https://acme.com/jobs/1?a=1",
        )

    def test_looks_like_id(self):
        for name in ("id", "jobId", "gh_jid", "postingid", "requisition", "job"):
            self.assertTrue(looks_like_id(name), name)
        for name in ("source", "ref", "lang", "mode", "company"):
            self.assertFalse(looks_like_id(name), name)


class PostingUrlKeyTests(SimpleTestCase):
    def test_copies_of_a_link_share_a_key(self):
        key = posting_url_key("https://jobs.lever.co/acme/abc-123")
        self.assertEqual(key, "jobs.lever.co/acme/abc-123")
        for copy in (
            "http://jobs.lever.co/acme/abc-123",
            "https://www.jobs.lever.co/acme/abc-123",
            "HTTPS://Jobs.Lever.co/Acme/ABC-123",
            "https://jobs.lever.co/acme/abc-123/",
            "https://jobs.lever.co/acme/abc-123?utm_source=x&lever-source=LinkedIn",
            "https://jobs.lever.co/acme/abc-123#apply",
            "  https://jobs.lever.co:443/acme/abc-123  ",
        ):
            self.assertEqual(posting_url_key(copy), key, copy)

    def test_parameters_count_whatever_their_order(self):
        self.assertEqual(
            posting_url_key(
                "https://career5.sapsf.com/career?company=Acme&career_job_req_id=88"
            ),
            posting_url_key(
                "https://career5.sapsf.com/career?career_job_req_id=88&company=Acme&utm_id=1"
            ),
        )
        self.assertEqual(
            posting_url_key("https://acme.com/c?q=a+b"),
            posting_url_key("https://acme.com/c?q=a%20b"),
        )

    def test_different_postings_have_different_keys(self):
        for first, second in (
            # Taleo names the job with ?job=, so it can't be dropped.
            (
                "https://acme.taleo.net/jobdetail.ftl?job=1",
                "https://acme.taleo.net/jobdetail.ftl?job=2",
            ),
            ("https://acme.com/careers?gh_jid=1", "https://acme.com/careers?gh_jid=2"),
            ("https://jobs.lever.co/acme/1", "https://jobs.lever.co/acme/2"),
            ("https://jobs.lever.co/acme/1", "https://jobs.lever.co/other/1"),
            # A #/route can name the job; an anchor like #apply can't.
            ("https://acme.com/jobs#/position/1", "https://acme.com/jobs#/position/2"),
        ):
            self.assertNotEqual(posting_url_key(first), posting_url_key(second), first)

    def test_non_links_have_no_key(self):
        for value in (
            "",
            "not a link",
            "ftp://acme.com/jobs/1",
            "mailto:jobs@acme.com",
        ):
            self.assertEqual(posting_url_key(value), "", value)


class FormTests(TestCase):
    user: ClassVar[User]
    company: ClassVar[Company]

    @classmethod
    @override
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user("owner@example.com", "x")
        cls.company = Company.objects.create(user_owner=cls.user, name="Acme")

    @override
    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_the_job_form_saves_a_clean_link(self):
        data = {"company": str(self.company.id), "title": "E", "posting_url": TRACKED}
        _ = self.client.post(reverse("tracker:job_add"), data)
        job = Job.objects.get()
        self.assertEqual(job.posting_url, CLEAN)
        _ = self.client.post(
            reverse("tracker:job_edit", args=[job.id]),
            {**data, "posting_url": CLEAN + "?utm_source=email&job_id=5"},
        )
        job.refresh_from_db()
        self.assertEqual(job.posting_url, CLEAN + "?job_id=5")

    def test_a_long_link_is_accepted_if_it_fits_once_cleaned(self):
        long = CLEAN + "?utm_content=" + "x" * 300
        data = {"company": str(self.company.id), "title": "E", "posting_url": long}
        response = self.client.post(reverse("tracker:job_add"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Job.objects.get().posting_url, CLEAN)
        too_long = "https://acme.com/" + "x" * 200 + "?utm_source=x"
        response = self.client.post(
            reverse("tracker:job_add"), {**data, "posting_url": too_long}
        )
        self.assertEqual(response.status_code, 200)  # still too long once cleaned
        self.assertContains(response, "at most 200 characters")

    def test_the_admin_saves_a_clean_link(self):
        root = User.objects.create_superuser("root@example.com", "x")
        self.client.force_login(root)
        job = Job.objects.create(company=self.company, title="E")
        url = reverse("admin:tracker_job_change", args=[job.id])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        form = {
            "company": str(self.company.id),
            "title": "E",
            "posting_url": TRACKED,
            "location_city": "",
            "location_state": "",
            "workplace_type": "",
            "description": "",
            "salary_min": "",
            "salary_max": "",
            "is_deleted": "",
            "applications-TOTAL_FORMS": "0",
            "applications-INITIAL_FORMS": "0",
            "applications-MIN_NUM_FORMS": "0",
            "applications-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(url, form)
        self.assertEqual(response.status_code, 302, response.content.decode()[:2000])
        job.refresh_from_db()
        self.assertEqual(job.posting_url, CLEAN)


class ApiTests(ApiTestCase):
    def test_the_api_saves_a_clean_link(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        job = self.ok(
            "POST",
            "jobs",
            {"company": str(company.id), "title": "E", "posting_url": TRACKED},
            status=201,
        )
        self.assertEqual(job["posting_url"], CLEAN)
        job = self.ok(
            "PATCH",
            f"jobs/{job['id']}",
            {"posting_url": CLEAN + "?gh_jid=1&utm_source=x"},
        )
        self.assertEqual(job["posting_url"], CLEAN + "?gh_jid=1")

    def test_the_posting_url_filter_matches_copies_of_the_link(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        _ = self.ok(
            "POST",
            "jobs",
            {"company": str(company.id), "title": "Saved", "posting_url": CLEAN},
            status=201,
        )
        _ = self.ok(
            "POST",
            "jobs",
            {
                "company": str(company.id),
                "title": "Similar",
                "posting_url": CLEAN + "4",
            },
            status=201,
        )
        for copy in ("http://www.jobs.lever.co/acme/ABC-123/", CLEAN + "#apply"):
            page: Json = self.ok("GET", "jobs?" + urlencode({"posting_url": copy}))
            self.assertEqual(names(page, "title"), ["Saved"], copy)
        self.assertEqual(
            names(self.ok("GET", "jobs?posting_url=not+a+link"), "title"), []
        )

    def test_the_posting_url_filter_cleans_the_link_too(self):
        company = Company.objects.create(user_owner=self.user, name="Acme")
        _ = self.ok(
            "POST",
            "jobs",
            {"company": str(company.id), "title": "Saved", "posting_url": TRACKED},
            status=201,
        )
        other_tracking = CLEAN + "?utm_source=newsletter&fbclid=abc"
        page: Json = self.ok(
            "GET", "jobs?" + urlencode({"posting_url": other_tracking})
        )
        self.assertEqual(names(page, "title"), ["Saved"])
        long = CLEAN + "?utm_content=" + "x" * 1000
        self.assertEqual(
            names(self.ok("GET", "jobs?" + urlencode({"posting_url": long})), "title"),
            ["Saved"],
        )
