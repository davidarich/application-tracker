"""Keeping a parsed resume in the session between upload and review.

Sessions store JSON, so dates are kept as ISO strings ("2021-03-01").
"""

from dataclasses import asdict
from datetime import date
from typing import cast

from .parser import CertificationEntry, EducationEntry, ResumeExtraction, WorkEntry

type JSONDict = dict[str, object]


def encode_value(value: object) -> object:
    return value.isoformat() if isinstance(value, date) else value


def encode_entry(entry: WorkEntry | EducationEntry | CertificationEntry) -> JSONDict:
    fields = cast(dict[str, object], asdict(entry))
    return {key: encode_value(value) for key, value in fields.items()}


def to_session(extraction: ResumeExtraction) -> JSONDict:
    return {
        "summary": extraction.summary,
        "work": [encode_entry(entry) for entry in extraction.work],
        "education": [encode_entry(entry) for entry in extraction.education],
        "certifications": [encode_entry(entry) for entry in extraction.certifications],
        "skill_ids": list(extraction.skill_ids),
        "warnings": list(extraction.warnings),
    }


def text(data: JSONDict, key: str) -> str:
    value = data.get(key, "")
    return value if isinstance(value, str) else ""


def day(data: JSONDict, key: str) -> date | None:
    value = data.get(key)
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def flag(data: JSONDict, key: str) -> bool:
    return data.get(key) is True


def items(data: JSONDict, key: str) -> list[JSONDict]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [
        cast(JSONDict, item)
        for item in cast(list[object], value)
        if isinstance(item, dict)
    ]


def strings(data: JSONDict, key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[object], value) if isinstance(item, str)]


def from_session(stored: object) -> ResumeExtraction | None:
    """The parsed resume, or None if what's stored isn't one (or is damaged)."""
    if not isinstance(stored, dict):
        return None
    data = cast(JSONDict, stored)
    try:
        return ResumeExtraction(
            summary=text(data, "summary"),
            work=[
                WorkEntry(
                    title=text(item, "title"),
                    employer=text(item, "employer"),
                    location=text(item, "location"),
                    start_date=day(item, "start_date"),
                    end_date=day(item, "end_date"),
                    description=text(item, "description"),
                    uncertain=flag(item, "uncertain"),
                )
                for item in items(data, "work")
            ],
            education=[
                EducationEntry(
                    institution=text(item, "institution"),
                    degree=text(item, "degree"),
                    field_of_study=text(item, "field_of_study"),
                    start_date=day(item, "start_date"),
                    end_date=day(item, "end_date"),
                    description=text(item, "description"),
                    uncertain=flag(item, "uncertain"),
                    in_progress=flag(item, "in_progress"),
                )
                for item in items(data, "education")
            ],
            certifications=[
                CertificationEntry(
                    name=text(item, "name"),
                    issuer=text(item, "issuer"),
                    issued_on=day(item, "issued_on"),
                    expires_on=day(item, "expires_on"),
                    credential_id=text(item, "credential_id"),
                    uncertain=flag(item, "uncertain"),
                    in_progress=flag(item, "in_progress"),
                )
                for item in items(data, "certifications")
            ],
            skill_ids=strings(data, "skill_ids"),
            warnings=strings(data, "warnings"),
        )
    except ValueError:  # a damaged date
        return None
