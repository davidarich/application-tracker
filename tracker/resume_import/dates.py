"""Finding and parsing the dates in resume text.

Resumes write dates many ways: "Mar 2021", "March, 2021", "03/2021",
"2021-03", "Mar '21" or just "2021", and ranges like "2019 - Present".
Dates are kept to the month, as the resume form stores them.
"""

import re
from dataclasses import dataclass
from datetime import date

import dateparser

MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    + r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
DATE = (
    rf"(?:{MONTH},?\s*(?:\d{{4}}|'\d{{2}})"  # Mar 2021, March, 2021, Mar '21
    + r"|(?:0?[1-9]|1[0-2])\s*/\s*\d{4}"  # 03/2021
    + r"|\d{4}\s*[-/.]\s*(?:0?[1-9]|1[0-2])(?!\d)"  # 2021-03
    + r"|(?:19|20)\d{2})"  # 2021
)
ONGOING = r"(?:present|current(?:ly)?|now|today|ongoing|date)"
RANGE_RE = re.compile(
    rf"(?<![\w'])(?P<start>{DATE})\s*(?:-|–|—|to|until|through|thru)\s*"
    + rf"(?P<end>{DATE}|{ONGOING})(?!\w)",
    re.IGNORECASE,
)
DATE_RE = re.compile(rf"(?<![\w'])(?:{DATE})(?!\w)", re.IGNORECASE)
TWO_DIGIT_YEAR_RE = re.compile(rf"({MONTH}),?\s*'(\d{{2}})", re.IGNORECASE)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")

DATEPARSER_SETTINGS = {
    "PREFER_DAY_OF_MONTH": "first",
    "REQUIRE_PARTS": ["month", "year"],
    "DATE_ORDER": "MDY",
}


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date | None  # None when ongoing ("Present")
    span: tuple[int, int]  # where the range is in the text


@dataclass(frozen=True)
class FoundDate:
    value: date
    span: tuple[int, int]


def parse_date(text: str, today: date | None = None) -> date | None:
    """The first of the month `text` names, or None if it isn't a date."""
    cleaned = " ".join(text.split()).strip(" .,")
    if YEAR_RE.fullmatch(cleaned):
        return date(int(cleaned), 1, 1)
    two_digit = TWO_DIGIT_YEAR_RE.fullmatch(cleaned)
    if two_digit:
        current_year = (today or date.today()).year
        year = 2000 + int(two_digit.group(2))
        if year > current_year + 5:
            year -= 100
        cleaned = f"{two_digit.group(1)} {year}"
    parsed = dateparser.parse(cleaned, languages=["en"], settings=DATEPARSER_SETTINGS)
    if parsed is None:
        return None
    return date(parsed.year, parsed.month, 1)


def find_range(text: str) -> DateRange | None:
    """The first date range in `text`, e.g. "Jan 2020 – Present"."""
    for match in RANGE_RE.finditer(text):
        start = parse_date(match.group("start"))
        end_text = match.group("end")
        ongoing = re.fullmatch(ONGOING, end_text, re.IGNORECASE) is not None
        end = None if ongoing else parse_date(end_text)
        if start is not None and (ongoing or end is not None):
            return DateRange(start, end, match.span())
    return None


def find_dates(text: str) -> list[FoundDate]:
    """Every single date in `text`, in order."""
    found: list[FoundDate] = []
    for match in DATE_RE.finditer(text):
        value = parse_date(match.group())
        if value is not None:
            found.append(FoundDate(value, match.span()))
    return found


def remove_span(text: str, span: tuple[int, int]) -> str:
    """`text` without the characters in `span`, tidied up."""
    return remove_spans(text, [span])


def remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` without the characters in any of `spans`, tidied up."""
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " + text[end:]
    return tidy(text)


def tidy(text: str) -> str:
    """Collapse spaces and strip leftover separators and brackets from the ends."""
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text).strip(" \t,;:|·•–—-")
    # Drop a bracket left without its partner ("(Remote" -> "Remote").
    if text.startswith("(") and ")" not in text:
        text = text[1:]
    if text.endswith(")") and "(" not in text:
        text = text[:-1]
    return text.strip(" \t,;:|·•–—-")
