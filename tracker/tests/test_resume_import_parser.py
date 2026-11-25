"""The rule-based resume parser (tracker/resume_import)."""

from datetime import date

from django.test import SimpleTestCase

from ..resume_import import (
    Line,
    ResumeReadError,
    SkillOption,
    extract_lines,
    parse_resume,
)
from ..resume_import.dates import find_range, parse_date
from ..resume_import.parser import (
    heading_kind,
    match_skills,
    parse_certifications,
    parse_education,
    parse_summary,
    parse_work,
)
from ..resume_import.pdf_text import Word, split_columns
from .pdf_builder import Text, build_pdf, column


def lines(*texts: str) -> list[Line]:
    return [Line(text) for text in texts]


class DateTests(SimpleTestCase):
    def test_parses_the_common_formats_to_the_month(self):
        today = date(2026, 11, 24)
        for text in (
            "Mar 2021",
            "March 2021",
            "March, 2021",
            "Mar. 2021",
            "03/2021",
            "2021-03",
            "Mar '21",
        ):
            with self.subTest(text):
                self.assertEqual(parse_date(text, today), date(2021, 3, 1))
        self.assertEqual(parse_date("2019"), date(2019, 1, 1))
        self.assertEqual(parse_date("Sep '98", today), date(1998, 9, 1))
        self.assertIsNone(parse_date("Present"))
        self.assertIsNone(parse_date("hello"))

    def test_finds_ranges(self):
        found = find_range("Senior Engineer\tJan 2020 – Present")
        assert found is not None
        self.assertEqual((found.start, found.end), (date(2020, 1, 1), None))
        found = find_range("06/2017 to 02/2021")
        assert found is not None
        self.assertEqual((found.start, found.end), (date(2017, 6, 1), date(2021, 2, 1)))
        found = find_range("2013 - 2017")
        assert found is not None
        self.assertEqual((found.start, found.end), (date(2013, 1, 1), date(2017, 1, 1)))
        self.assertIsNone(find_range("Graduated 2017"))
        self.assertIsNone(find_range("Phone 555-0100"))


class HeadingTests(SimpleTestCase):
    def test_recognizes_headings_in_many_styles(self):
        cases = {
            "EXPERIENCE": "work",
            "Professional Experience": "work",
            "Work History:": "work",
            "E X P E R I E N C E": "work",
            "Technical Skills": "skills",
            "Licenses & Certifications": "certifications",
            "Profile": "summary",
            "Education": "education",
            "Projects": "other",
        }
        for text, kind in cases.items():
            with self.subTest(text):
                self.assertEqual(heading_kind(Line(text, bold=True), 10), kind)

    def test_misspelled_headings_must_look_like_headings(self):
        self.assertEqual(heading_kind(Line("Experiance", bold=True), 10), "work")
        self.assertEqual(heading_kind(Line("Experiance", size=14), 10), "work")
        self.assertIsNone(heading_kind(Line("Experiance"), 10))

    def test_ordinary_lines_are_not_headings(self):
        self.assertIsNone(
            heading_kind(Line("Built the shipment tracking API", bold=True), 10)
        )
        self.assertIsNone(heading_kind(Line("Senior Software Engineer", bold=True), 10))


class WorkHistoryTests(SimpleTestCase):
    def test_title_then_employer_and_location_then_dates(self):
        [entry] = parse_work(
            lines(
                "Senior Software Engineer",
                "Driftwood Software Inc. | Austin, TX",
                "Mar 2021 – Present",
                "• Led the move from a monolith to services.",
                "• Cut API latency by 40% using",
                "caching.",
            )
        )
        self.assertEqual(entry.title, "Senior Software Engineer")
        self.assertEqual(entry.employer, "Driftwood Software Inc.")
        self.assertEqual(entry.location, "Austin, TX")
        self.assertEqual((entry.start_date, entry.end_date), (date(2021, 3, 1), None))
        self.assertEqual(
            entry.description,
            "- Led the move from a monolith to services.\n- Cut API latency by 40% using caching.",
        )
        self.assertFalse(entry.uncertain)

    def test_everything_on_one_line(self):
        [entry] = parse_work(lines("Data Analyst — Globex\tJun 2018 - Feb 2020"))
        self.assertEqual((entry.title, entry.employer), ("Data Analyst", "Globex"))
        self.assertEqual(entry.end_date, date(2020, 2, 1))

    def test_employer_first_then_title(self):
        [entry] = parse_work(
            lines("Harbor Logistics", "Software Engineer\t06/2017 - 02/2021")
        )
        self.assertEqual(
            (entry.title, entry.employer), ("Software Engineer", "Harbor Logistics")
        )

    def test_commas_and_bracketed_dates(self):
        [entry] = parse_work(
            lines("Product Manager, Initech, Remote (Jan 2019 - Dec 2020)")
        )
        self.assertEqual(
            (entry.title, entry.employer, entry.location),
            ("Product Manager", "Initech", "Remote"),
        )

    def test_title_at_company(self):
        [entry] = parse_work(lines("Backend Developer at Acme Corp", "2015 - 2017"))
        self.assertEqual(
            (entry.title, entry.employer), ("Backend Developer", "Acme Corp")
        )

    def test_employer_on_the_line_after_the_dates(self):
        [entry] = parse_work(
            lines("Staff Engineer\t2020 - Present", "Globex", "• Did things.")
        )
        self.assertEqual((entry.title, entry.employer), ("Staff Engineer", "Globex"))
        self.assertEqual(entry.description, "- Did things.")

    def test_guesses_are_flagged(self):
        [entry] = parse_work(lines("Blue Sky\tGreen Field\t2015 - 2016"))
        self.assertTrue(entry.uncertain)
        [entry] = parse_work(lines("Wrangler\t2015 - 2016"))
        self.assertTrue(entry.uncertain)
        self.assertEqual(entry.employer, "")

    def test_career_breaks_have_no_employer_and_are_not_guesses(self):
        for title in ("Medical Leave", "Sabbatical", "Parental Leave", "Career Break"):
            with self.subTest(title):
                [entry] = parse_work(lines(f"{title}\t2020 - 2021", "Austin, TX"))
                self.assertEqual((entry.title, entry.employer), (title, ""))
                self.assertEqual(entry.location, "Austin, TX")
                self.assertFalse(entry.uncertain)

    def test_a_job_without_an_employer_is_still_flagged(self):
        [entry] = parse_work(lines("Software Engineer\t2020 - 2021"))
        self.assertEqual(entry.employer, "")
        self.assertTrue(entry.uncertain)

    def test_several_positions(self):
        entries = parse_work(
            lines(
                "Lead Engineer",
                "Acme Inc.\t2021 - Present",
                "• Led a team of five.",
                "Engineer",
                "Globex LLC\t2018 - 2021",
                "• Built the billing system.",
            )
        )
        self.assertEqual([e.employer for e in entries], ["Acme Inc.", "Globex LLC"])
        self.assertEqual([e.title for e in entries], ["Lead Engineer", "Engineer"])
        self.assertEqual(entries[0].description, "- Led a team of five.")

    def test_descriptions_are_dash_lists_whatever_the_bullet_symbol(self):
        [entry] = parse_work(
            lines(
                "Engineer\tAcme Inc.\t2020 - 2021",
                "● Built the API",
                "• Wrote the docs that",
                "everyone reads",
                "- Ran the on-call rota",
                "* Hired two engineers",
            )
        )
        self.assertEqual(
            entry.description,
            "- Built the API\n- Wrote the docs that everyone reads\n"
            + "- Ran the on-call rota\n- Hired two engineers",
        )

    def test_a_description_without_bullets_is_one_item(self):
        [entry] = parse_work(
            lines(
                "Engineer\tAcme Inc.\t2020 - 2021",
                "Built the API and",
                "wrote the docs.",
            )
        )
        self.assertEqual(entry.description, "- Built the API and wrote the docs.")


class EducationTests(SimpleTestCase):
    def test_school_degree_field_and_dates(self):
        [entry] = parse_education(
            lines(
                "State University",
                "Bachelor of Science in Computer Science\t2013 – 2017",
                "GPA 3.8",
            )
        )
        self.assertEqual(entry.institution, "State University")
        self.assertEqual(
            (entry.degree, entry.field_of_study),
            ("Bachelor of Science", "Computer Science"),
        )
        self.assertEqual(
            (entry.start_date, entry.end_date), (date(2013, 1, 1), date(2017, 1, 1))
        )
        self.assertEqual(entry.description, "GPA 3.8")
        self.assertFalse(entry.uncertain)

    def test_abbreviated_degree_on_one_line_and_several_schools(self):
        entries = parse_education(
            lines(
                "MBA, Business Administration, Northfield College, May 2020",
                "B.S. Mathematics, State University, 2012",
            )
        )
        self.assertEqual(
            [(e.institution, e.degree, e.field_of_study, e.end_date) for e in entries],
            [
                (
                    "Northfield College",
                    "MBA",
                    "Business Administration",
                    date(2020, 5, 1),
                ),
                ("State University", "B.S.", "Mathematics", date(2012, 1, 1)),
            ],
        )

    def test_expected_and_ongoing_studies_are_in_progress(self):
        [expected] = parse_education(
            lines(
                "State University",
                "Master of Science in Data Science",
                "Expected May 2026",
            )
        )
        self.assertEqual(
            (expected.end_date, expected.in_progress), (date(2026, 5, 1), True)
        )
        self.assertEqual(
            expected.description, ""
        )  # "Expected" isn't left behind as a detail
        [ongoing] = parse_education(
            lines("Northfield College", "MBA\tSep 2024 – Present")
        )
        self.assertEqual(
            (ongoing.start_date, ongoing.end_date, ongoing.in_progress),
            (date(2024, 9, 1), None, True),
        )
        [finished] = parse_education(
            lines("State University", "B.S. Math\t2010 – 2014")
        )
        self.assertFalse(finished.in_progress)

    def test_a_degree_without_a_school_is_flagged(self):
        [entry] = parse_education(lines("Bachelor of Arts in History"))
        self.assertTrue(entry.uncertain)


class CertificationTests(SimpleTestCase):
    def test_issuer_dates_and_id_on_following_lines(self):
        [cert] = parse_certifications(
            lines(
                "AWS Certified Solutions Architect – Associate",
                "Amazon Web Services",
                "Issued Apr 2022 · Expires Apr 2025 · Credential ID ABC-12345",
            )
        )
        self.assertEqual(cert.name, "AWS Certified Solutions Architect – Associate")
        self.assertEqual(cert.issuer, "Amazon Web Services")
        self.assertEqual(
            (cert.issued_on, cert.expires_on), (date(2022, 4, 1), date(2025, 4, 1))
        )
        self.assertEqual(cert.credential_id, "ABC-12345")

    def test_expected_certifications_are_in_progress(self):
        certs = parse_certifications(
            lines(
                "Certified Kubernetes Administrator (CKA)",
                "Cloud Native Computing Foundation",
                "Expected completion November 2026",
                "• Google Cloud Professional Data Engineer (in progress)",
            )
        )
        self.assertEqual(
            [(c.name, c.issued_on, c.in_progress, c.uncertain) for c in certs],
            [
                (
                    "Certified Kubernetes Administrator (CKA)",
                    date(2026, 11, 1),
                    True,
                    False,
                ),
                ("Google Cloud Professional Data Engineer", None, True, False),
            ],
        )

    def test_one_line_forms(self):
        certs = parse_certifications(
            lines(
                "• Certified Kubernetes Administrator (CNCF), 2023",
                "• Professional Scrum Master I | Scrum.org | Jan 2021",
                "• Google Cloud Professional Data Engineer",
            )
        )
        self.assertEqual(
            [(c.name, c.issuer, c.issued_on) for c in certs],
            [
                ("Certified Kubernetes Administrator", "CNCF", date(2023, 1, 1)),
                ("Professional Scrum Master I", "Scrum.org", date(2021, 1, 1)),
                ("Google Cloud Professional Data Engineer", "Google Cloud", None),
            ],
        )


SKILLS = [
    SkillOption("1", "Python"),
    SkillOption("2", "Go"),
    SkillOption("3", "Kubernetes"),
    SkillOption("4", "Spring Boot"),
    SkillOption("5", "C#"),
    SkillOption("6", "Vue.js"),
    SkillOption("7", "Java"),
]


class SkillTests(SimpleTestCase):
    def names(self, body: list[Line], skills_section: list[Line]) -> list[str]:
        ids = match_skills(body + skills_section, skills_section, SKILLS)
        return [skill.name for skill in SKILLS if skill.id in ids]

    def test_matches_names_and_aliases_anywhere(self):
        found = self.names(lines("Built services in Python and C# on K8s with Vue"), [])
        self.assertEqual(found, ["Python", "Kubernetes", "C#", "Vue.js"])

    def test_everyday_words_only_count_in_the_skills_section(self):
        self.assertEqual(
            self.names(lines("Ready to go the extra mile; Go-getter"), []), []
        )
        self.assertEqual(self.names([], lines("Go, Python")), ["Python", "Go"])
        self.assertEqual(self.names([], lines("go, python")), ["Python"])

    def test_whole_words_only(self):
        self.assertEqual(self.names(lines("JavaScript and TypeScript"), []), [])

    def test_fuzzy_matches_skills_section_items(self):
        self.assertEqual(self.names([], lines("Spring-Boot (3 yrs)")), ["Spring Boot"])


class SummaryTests(SimpleTestCase):
    def test_summary_section_or_sentences_above_the_first_heading(self):
        self.assertEqual(
            parse_summary(lines("Backend engineer.", "Loves APIs."), []),
            "Backend engineer. Loves APIs.",
        )
        header = lines(
            "Jason Miller",
            "jason@example.com · 555-0100",
            "Backend engineer with eight years of experience building APIs and data pipelines.",
        )
        self.assertEqual(
            parse_summary([], header),
            "Backend engineer with eight years of experience building APIs and data pipelines.",
        )


class ColumnTests(SimpleTestCase):
    def word(self, x0: float, top: float, text: str = "word") -> Word:
        return Word(text, x0, x0 + 30, top, 10, False)

    def test_splits_a_sidebar_from_the_main_column(self):
        sidebar = [self.word(40, 100 + 16 * i, f"side{i}") for i in range(8)]
        main = [
            self.word(x, 100 + 16 * i, f"main{i}")
            for i in range(20)
            for x in (220, 260, 300, 340)
        ]
        columns = split_columns(sidebar + main, 612)
        self.assertEqual(len(columns), 2)
        self.assertEqual(columns[0], sidebar)

    def test_single_column_pages_are_left_alone(self):
        words = [
            self.word(x, 100 + 16 * i) for i in range(20) for x in range(40, 560, 35)
        ]
        self.assertEqual(split_columns(words, 612), [words])


class PdfTests(SimpleTestCase):
    def test_two_column_resume_end_to_end(self):
        b, n = True, False
        main = column(
            200,
            120,
            [
                ("EXPERIENCE", 12, b),
                ("Senior Software Engineer", 10, b),
                ("Driftwood Software Inc. | Austin, TX", 10, n),
                ("• Led the move from a monolith to services.", 10, n),
                ("EDUCATION", 12, b),
                ("State University", 10, b),
                ("Bachelor of Science in Computer Science", 10, n),
            ],
        )
        side = column(
            40,
            120,
            [("SKILLS", 12, b), ("Python, Go", 10, n), ("K8s", 10, n), ("Java", 10, n)],
        )
        dates = [
            Text(470, main[2].y, "Mar 2021 – Present"),
            Text(470, main[6].y, "2013 – 2017"),
        ]
        header = [Text(40, 40, "Jason Miller", 20, True)]
        result = parse_resume(
            extract_lines(build_pdf([header + side + main + dates])), SKILLS
        )
        [job] = result.work
        self.assertEqual(
            (job.title, job.employer, job.location),
            ("Senior Software Engineer", "Driftwood Software Inc.", "Austin, TX"),
        )
        self.assertEqual(job.start_date, date(2021, 3, 1))
        [school] = result.education
        self.assertEqual(
            (school.institution, school.end_date),
            ("State University", date(2017, 1, 1)),
        )
        self.assertEqual(
            [skill.name for skill in SKILLS if skill.id in result.skill_ids],
            ["Python", "Go", "Kubernetes", "Java"],
        )
        self.assertEqual(result.warnings, [])

    def test_unreadable_files(self):
        with self.assertRaisesMessage(ResumeReadError, "couldn't be read as a PDF"):
            _ = extract_lines(b"%PDF-1.4 not really a pdf")
        with self.assertRaisesMessage(ResumeReadError, "No text was found"):
            _ = extract_lines(build_pdf([[]]))
        with self.assertRaisesMessage(ResumeReadError, "more than 10 pages"):
            _ = extract_lines(build_pdf([[Text(40, 40, "Page")] for _ in range(11)]))

    def test_no_headings_warns(self):
        result = parse_resume(
            lines("Some text without any headings at all, just words."), SKILLS
        )
        self.assertIn("No section headings", result.warnings[0])
