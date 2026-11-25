"""Filling in the resume from an uploaded PDF, using rules rather than AI.

pdf_text reads the PDF's lines (in reading order, with font size and weight),
dates finds and parses dates, and parser turns the lines into resume entries.
The user reviews everything before it's saved (see tracker/resume_views.py).
"""

from .parser import (
    CertificationEntry,
    EducationEntry,
    ResumeExtraction,
    SkillOption,
    WorkEntry,
    parse_resume,
)
from .pdf_text import Line, ResumeReadError, extract_lines

__all__ = [
    "CertificationEntry",
    "EducationEntry",
    "Line",
    "ResumeExtraction",
    "ResumeReadError",
    "SkillOption",
    "WorkEntry",
    "extract_lines",
    "parse_resume",
]
