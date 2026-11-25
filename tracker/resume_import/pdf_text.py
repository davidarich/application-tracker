"""Text lines from a PDF, in reading order, with their font size and weight.

Resumes are often laid out in two columns (a sidebar with skills and contact
details next to the main experience column). Reading such a page straight
across mixes the columns line by line, so each page is checked for a vertical
gap that splits it into columns, and the columns are read one after another.
"""

import io
import itertools
import statistics
from dataclasses import dataclass
from typing import cast

import pdfplumber

from .dates import DATE_RE

MAX_PAGES = 10
# Fewer characters than this means the PDF is probably a scanned image.
MIN_TEXT_CHARS = 40
# Words whose tops are this close (in points) are on the same line.
LINE_TOLERANCE = 3.0
BOLD_MARKERS = ("bold", "black", "heavy", "semibold", "demi")
# The narrowest empty band (in points) between two columns.
COLUMN_GAP = 12.0


class ResumeReadError(Exception):
    """The PDF couldn't be read; the message is shown to the user."""


@dataclass(frozen=True)
class Line:
    """One line of text. A big horizontal gap between words is kept as a tab,
    since it usually separates fields (e.g. a job title and its dates)."""

    text: str
    size: float = 10.0
    bold: bool = False


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    size: float
    bold: bool


def extract_lines(data: bytes) -> list[Line]:
    """The text lines of a PDF, column by column and page by page."""
    lines: list[Line] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise ResumeReadError(
                    f"This PDF has more than {MAX_PAGES} pages. Upload just your resume."
                )
            for page in pdf.pages:
                raw_words = page.extract_words(extra_attrs=["fontname", "size"])
                words = [to_word(raw) for raw in raw_words]
                for column in split_columns(words, float(page.width)):
                    lines.extend(group_lines(column))
    except ResumeReadError:
        raise
    except Exception as error:  # pdfminer raises many kinds of errors for bad PDFs
        raise ResumeReadError(
            "This file couldn't be read as a PDF. It may be damaged or password protected."
        ) from error
    if sum(len(line.text) for line in lines) < MIN_TEXT_CHARS:
        raise ResumeReadError(
            "No text was found in this PDF. It may be a scanned image; "
            + "upload a PDF exported from a word processor instead."
        )
    return lines


def to_word(raw: dict[str, object]) -> Word:
    """A word from pdfplumber's untyped word dictionary."""
    fontname = str(raw.get("fontname", "")).lower()
    return Word(
        text=str(raw["text"]),
        x0=float(cast(float, raw["x0"])),
        x1=float(cast(float, raw["x1"])),
        top=float(cast(float, raw["top"])),
        size=float(cast(float, raw.get("size", 10.0))),
        bold=any(marker in fontname for marker in BOLD_MARKERS),
    )


def split_columns(words: list[Word], width: float) -> list[list[Word]]:
    """Split a page's words into columns, if it has a clear vertical gap.

    The gap may be crossed by a few lines that span the page (usually the
    name and contact details at the top); those lines come first.
    """
    if len(words) < 20 or width <= 0:
        return [words]
    allowed_crossings = max(2, len(words) // 20)
    best: tuple[int, list[list[Word]]] | None = None  # (crossings, columns)
    for percent in range(25, 76):
        x = width * percent / 100
        crossing = [word for word in words if crosses(word, x)]
        if len(crossing) > allowed_crossings:
            continue
        spanning = [
            word
            for word in words
            if any(abs(word.top - other.top) <= LINE_TOLERANCE for other in crossing)
        ]
        rest = [word for word in words if word not in spanning]
        left = [word for word in rest if word.x1 <= x]
        right = [word for word in rest if word.x0 >= x]
        # Each column needs some words (a narrow sidebar of skills counts),
        # and real text: a "column" of dates at the edge of the page is just
        # dates beside the job titles.
        if min(len(left), len(right)) < max(5, len(words) * 0.05):
            continue
        if mostly_dates(left) or mostly_dates(right):
            continue
        if best is None or len(crossing) < best[0]:
            best = (len(crossing), [spanning, left, right])
    if best is None:
        return [words]
    return [column for column in best[1] if column]


def mostly_dates(words: list[Word]) -> bool:
    """Are most of these words' lines dates (like right-aligned job dates)?"""
    rows = [" ".join(word.text for word in row) for row in rows_of(words)]
    dated = sum(1 for row in rows if DATE_RE.search(row))
    return bool(rows) and dated * 10 >= len(rows) * 6


def rows_of(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines, top to bottom and left to right."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(rows[-1][0].top - word.top) <= LINE_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w.x0)
    return rows


def crosses(word: Word, x: float) -> bool:
    """Does `word` reach into the column gap centred on `x`? The gap must be
    wider than the space between words, or every space would be a gap."""
    return word.x0 < x + COLUMN_GAP / 2 and word.x1 > x - COLUMN_GAP / 2


def group_lines(words: list[Word]) -> list[Line]:
    """Join words into text lines, top to bottom and left to right."""
    lines: list[Line] = []
    for row in rows_of(words):
        size = max(word.size for word in row)
        text = row[0].text
        for previous, word in itertools.pairwise(row):
            gap = word.x0 - previous.x1
            text += ("\t" if gap > max(12.0, size * 1.5) else " ") + word.text
        bold_chars = sum(len(word.text) for word in row if word.bold)
        total_chars = sum(len(word.text) for word in row)
        lines.append(Line(text=text, size=size, bold=bold_chars * 2 > total_chars))
    return lines


def body_size(lines: list[Line]) -> float:
    """The usual font size of the body text (headings are bigger)."""
    sizes = [line.size for line in lines if len(line.text) > 20] or [
        line.size for line in lines
    ]
    return statistics.median(sizes) if sizes else 10.0
