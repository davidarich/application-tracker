"""Turn a resume's text lines into resume entries, using rules (no AI).

1. Split the lines into sections at headings. A heading is a short line that
   fuzzy-matches a known section name ("Work History", "EXPERIENCE",
   "Professional Experience"...); unless it matches exactly, it must also
   look like a heading (bold, bigger, ALL CAPS or ending in a colon).
2. Parse each section with its own rules (see the parse_* functions).

Results are a best guess: entries the rules aren't sure about are flagged,
and everything is reviewed by the user before it's saved.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from rapidfuzz import fuzz, process

from .dates import (
    DateRange,
    find_dates,
    find_range,
    remove_span,
    remove_spans,
    tidy,
)
from .pdf_text import Line, body_size

# --- Section headings ---------------------------------------------------------------------

SECTION_NAMES: dict[str, tuple[str, ...]] = {
    "summary": (
        "summary",
        "professional summary",
        "career summary",
        "executive summary",
        "profile",
        "professional profile",
        "about",
        "about me",
        "objective",
        "career objective",
        "overview",
        "personal statement",
    ),
    "work": (
        "experience",
        "work experience",
        "professional experience",
        "relevant experience",
        "employment",
        "employment history",
        "work history",
        "career history",
        "professional background",
    ),
    "skills": (
        "skills",
        "technical skills",
        "key skills",
        "core skills",
        "core competencies",
        "competencies",
        "technologies",
        "tech stack",
        "tools and technologies",
        "skills and tools",
        "areas of expertise",
        "expertise",
    ),
    "education": (
        "education",
        "academic background",
        "education and training",
        "academic history",
    ),
    "certifications": (
        "certifications",
        "certification",
        "certificates",
        "licenses",
        "licenses and certifications",
        "certifications and licenses",
        "professional certifications",
        "credentials",
        "courses and certifications",
    ),
    # Sections that aren't imported, but end the section before them.
    "other": (
        "projects",
        "personal projects",
        "awards",
        "honors",
        "honors and awards",
        "publications",
        "volunteer",
        "volunteering",
        "volunteer experience",
        "interests",
        "hobbies",
        "languages",
        "references",
        "activities",
        "leadership",
        "achievements",
        "contact",
        "links",
    ),
}
HEADING_KINDS = {name: kind for kind, names in SECTION_NAMES.items() for name in names}
HEADING_CHOICES = list(HEADING_KINDS)
HEADING_MIN_SCORE = 85

BULLET_RE = re.compile(r"^\s*[•●▪◦‣∙·*\-–—]\s+")

# --- Work history: telling a job title from an employer ------------------------------------

ROLE_RE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|manager|director|lead|head|chief|"
    + r"officer|analyst|scientist|designer|consultant|specialist|administrator|admin|"
    + r"intern|associate|assistant|coordinator|technician|representative|advisor|adviser|"
    + r"strategist|researcher|professor|teacher|lecturer|instructor|nurse|accountant|"
    + r"co-?founder|founder|owner|president|vp|cto|ceo|cfo|coo|cio|sre|devops|tester|qa|"
    + r"product owner|scrum master|editor|writer|recruiter|contractor|freelancer|"
    + r"supervisor|operator|agent|clerk|executive)s?\b",
    re.IGNORECASE,
)
SENIORITY_RE = re.compile(
    r"\b(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|entry[- ]level|"
    + r"[iv]{1,3})\b",
    re.IGNORECASE,
)
# Career breaks: positions with no employer.
CAREER_BREAK_RE = re.compile(
    r"\b(?:(?:medical|parental|maternity|paternity|family|personal|bereavement|"
    + r"caregiver|caregiving)\s+leave|sabbatical|career\s+(?:break|gap|transition)|"
    + r"gap\s+year|professional\s+development|caregiv(?:er|ing)|"
    + r"(?:full-time|stay-at-home)\s+parent|homemaker|travel(?:l?ing)?|"
    + r"job\s+search(?:ing)?|relocation|time\s+off|leave\s+of\s+absence)\b",
    re.IGNORECASE,
)
LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|plc|gmbh|ag|"
    + r"s\.?a|pty|llp)\.?$",
    re.IGNORECASE,
)
ORG_WORD_RE = re.compile(
    r"\b(?:company|group|holdings|technologies|technology|systems|solutions|software|"
    + r"labs?|studios?|partners|consulting|agency|bank|university|college|hospital|"
    + r"health|media|logistics|energy|ventures|capital|foundation|institute|networks|"
    + r"services|industries|international|global|digital|analytics)\b",
    re.IGNORECASE,
)
LOCATION_SECOND_PARTS = (
    "USA|US|UK|United States|United Kingdom|Canada|Germany|India|Australia|Ireland|"
    + "Netherlands|France|Spain|Italy|Mexico|Brazil|Japan|Singapore|Poland|Portugal|"
    + "Sweden|Switzerland|New Zealand|Israel"
)
LOCATION_RE = re.compile(
    r"(?:^|,\s*|\t|\s+[|·•—–-]\s+)"
    + r"(?P<location>(?i:remote|hybrid|on-?site)"
    + r"|[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,2},\s*"
    + rf"(?:[A-Z]{{2}}|{LOCATION_SECOND_PARTS}))"
    + r"\s*$"
)
FRAGMENT_SEPARATORS_RE = re.compile(
    r"\t+|\s+[|·•—–]\s+|\s+-\s+|\s+at\s+|\s+@\s+", re.IGNORECASE
)

# --- Education ------------------------------------------------------------------------------

INSTITUTION_RE = re.compile(
    r"\b(?:university|college|institute|school|academy|polytechnic|conservatory)\b",
    re.IGNORECASE,
)
DEGREE_WORDS_RE = re.compile(
    r"\b(?:bachelor|master|associate of|associate's|doctor|doctorate|diploma|"
    + r"high school|certificate|graduate certificate)",
    re.IGNORECASE,
)
DEGREE_ABBREVIATION_RE = re.compile(
    r"(?<![A-Za-z])(?:B\.?S\.?c?|B\.?A\.?|B\.?Eng\.?|B\.?Tech|M\.?S\.?c?|M\.?A\.?|"
    + r"M\.?Eng\.?|MBA|M\.B\.A\.|Ph\.?D\.?|GED)(?![A-Za-z])"
)

# --- Certifications --------------------------------------------------------------------------

ISSUERS: dict[str, str] = {
    "aws": "Amazon Web Services",
    "amazon web services": "Amazon Web Services",
    "microsoft": "Microsoft",
    "azure": "Microsoft",
    "google cloud": "Google Cloud",
    "google": "Google",
    "gcp": "Google Cloud",
    "cisco": "Cisco",
    "comptia": "CompTIA",
    "oracle": "Oracle",
    "red hat": "Red Hat",
    "hashicorp": "HashiCorp",
    "cncf": "Cloud Native Computing Foundation",
    "cloud native computing foundation": "Cloud Native Computing Foundation",
    "linux foundation": "The Linux Foundation",
    "pmi": "Project Management Institute",
    "pmp": "Project Management Institute",
    "scrum alliance": "Scrum Alliance",
    "scrum.org": "Scrum.org",
    "isc2": "ISC2",
    "(isc)²": "ISC2",
    "isaca": "ISACA",
    "salesforce": "Salesforce",
    "kubernetes": "Cloud Native Computing Foundation",
    "terraform": "HashiCorp",
}
ISSUER_RE = re.compile(
    r"(?<![\w(])(?:" + "|".join(re.escape(name) for name in ISSUERS) + r")(?!\w)",
    re.IGNORECASE,
)
CREDENTIAL_ID_RE = re.compile(
    r"(?:credential\s*id|license\s*(?:no\.?|number)|certificate\s*(?:no\.?|number)|\bID\b)"
    + r"\s*[:#]?\s*(?P<id>[A-Za-z0-9][A-Za-z0-9-]{3,})",
    re.IGNORECASE,
)
EXPIRES_RE = re.compile(
    r"(?:expires?|expiration(?:\s*date)?|exp\.|valid\s*(?:until|through|thru))\s*:?\s*",
    re.IGNORECASE,
)
PENDING_RE = re.compile(
    r"\b(?:expected(?:\s+completion)?|anticipated|in\s+progress|pending)\b\s*:?",
    re.IGNORECASE,
)
RENEWAL_RE = re.compile(
    r"\b(?:re-?certified|renewed|recertification|renewal)\b(?:\s*(?:on|in))?\s*:?",
    re.IGNORECASE,
)
CERTIFICATION_WORDS_RE = re.compile(
    r"\b(?:certified|certification|certificate|professional|associate|practitioner|"
    + r"specialist|expert|fundamentals)\b",
    re.IGNORECASE,
)
ISSUED_WORDS_RE = re.compile(
    r"(?:issued|obtained|earned|awarded|completed)(?:\s*(?:on|in))?\s*:?\s*",
    re.IGNORECASE,
)

# --- Skills -----------------------------------------------------------------------------------

# Other ways resumes name the shared skills (only used if the skill exists).
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "JavaScript": ("JS", "ECMAScript", "ES6"),
    "Go": ("Golang",),
    "Kubernetes": ("K8s",),
    "PostgreSQL": ("Postgres",),
    "React": ("ReactJS", "React.js"),
    "Vue.js": ("Vue", "VueJS"),
    "Next.js": ("NextJS",),
    "Node.js": ("NodeJS",),
    "Angular": ("AngularJS",),
    ".NET": (".NET Core", "dotnet"),
    "C#": ("C Sharp", "CSharp"),
    "Ruby on Rails": ("Rails", "RoR"),
    "Spring Boot": ("SpringBoot",),
    "Argo CD": ("ArgoCD",),
    "Amazon S3": ("AWS S3", "S3"),
    "Amazon EC2": ("AWS EC2", "EC2"),
    "Amazon RDS": ("AWS RDS",),
    "Amazon DynamoDB": ("DynamoDB",),
    "Azure Kubernetes Service": ("AKS",),
    "Azure Blob Storage": ("Blob Storage",),
    "Google Cloud Run": ("Cloud Run",),
    "Google BigQuery": ("BigQuery",),
}
# Skill names that are also everyday words: only matched, with their exact
# capitalization, in the skills section ("Go" vs "go", "Swift" vs "swift").
AMBIGUOUS_SKILLS = {"Go", "R", "C", "Swift", "Spring", "Helm", "Ruby", "Rust", "Flask"}
SKILL_ITEM_SPLIT_RE = re.compile(r"[,;|•·/\t\n]|\s+and\s+")
SKILL_FUZZY_MIN_SCORE = 90


# --- Results ----------------------------------------------------------------------------------


@dataclass
class WorkEntry:
    title: str = ""
    employer: str = ""
    location: str = ""
    start_date: date | None = None
    end_date: date | None = None
    description: str = ""
    uncertain: bool = False


@dataclass
class EducationEntry:
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    start_date: date | None = None
    end_date: date | None = None
    description: str = ""
    uncertain: bool = False
    in_progress: bool = False  # end_date is the expected completion


@dataclass
class CertificationEntry:
    name: str = ""
    issuer: str = ""
    issued_on: date | None = None
    expires_on: date | None = None
    credential_id: str = ""
    uncertain: bool = False
    in_progress: bool = False  # issued_on is the expected completion


@dataclass
class ResumeExtraction:
    summary: str = ""
    work: list[WorkEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    certifications: list[CertificationEntry] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)  # matched shared skills
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillOption:
    """A shared skill the resume's skills are matched against."""

    id: str
    name: str


# --- Parsing ------------------------------------------------------------------------------------


def parse_resume(lines: list[Line], skills: Sequence[SkillOption]) -> ResumeExtraction:
    header, sections = split_sections(lines)
    result = ResumeExtraction()
    result.summary = parse_summary(sections.get("summary", []), header)
    result.work = parse_work(sections.get("work", []))
    result.education = parse_education(sections.get("education", []))
    result.certifications = parse_certifications(sections.get("certifications", []))
    result.skill_ids = match_skills(lines, sections.get("skills", []), skills)

    found = {kind for kind in sections if kind != "other"}
    if not found:
        result.warnings.append(
            "No section headings (like Experience or Education) were recognized, "
            + "so only skills could be found."
        )
    if sections.get("work") and not result.work:
        result.warnings.append(
            "No dates were found under your work history, so no positions were filled in."
        )
    uncertain = sum(
        1
        for entry in [*result.work, *result.education, *result.certifications]
        if entry.uncertain
    )
    if uncertain == 1:
        result.warnings.append(
            "1 entry couldn't be read with confidence and is marked “Check this”."
        )
    elif uncertain:
        result.warnings.append(
            f"{uncertain} entries couldn't be read with confidence and are marked “Check this”."
        )
    return result


def normalize_heading(text: str) -> str:
    words = text.replace("&", " and ").split()
    if len(words) > 2 and all(
        len(word) == 1 for word in words
    ):  # "E X P E R I E N C E"
        words = ["".join(words)]
    return " ".join(words).strip(" :.-–—|").lower()


def heading_kind(line: Line, normal_size: float) -> str | None:
    """The section a line starts, if it's a heading."""
    text = normalize_heading(line.text)
    if not text or len(text) > 40 or len(text.split()) > 5:
        return None
    match = process.extractOne(
        text, HEADING_CHOICES, scorer=fuzz.ratio, score_cutoff=HEADING_MIN_SCORE
    )
    if match is None:
        return None
    choice, score, _ = match
    looks_like_heading = (
        line.bold
        or line.size >= normal_size + 1
        or (line.text.isupper() and len(text) > 3)
        or line.text.rstrip().endswith(":")
    )
    if score < 100 and not looks_like_heading:
        return None
    return HEADING_KINDS[choice]


def split_sections(lines: list[Line]) -> tuple[list[Line], dict[str, list[Line]]]:
    """The lines before the first heading, and each section's lines."""
    normal_size = body_size(lines)
    header: list[Line] = []
    sections: dict[str, list[Line]] = {}
    current: list[Line] = header
    for line in lines:
        kind = heading_kind(line, normal_size)
        if kind is None:
            current.append(line)
        else:
            current = sections.setdefault(kind, [])
    return header, sections


def is_bullet(text: str) -> bool:
    return BULLET_RE.match(text) is not None


def bullet_list(lines: Sequence[Line]) -> str:
    """Paragraph text with each line starting "- ": a plain-text list that is
    easy to read, and that applicant tracking systems (ATS) parse reliably
    (unlike symbols such as "●")."""
    return "\n".join(f"- {line}" for line in join_lines(lines).splitlines())


def join_lines(lines: Sequence[Line]) -> str:
    """Paragraph text: a bullet starts a new line; other lines continue the last one."""
    paragraphs: list[str] = []
    for line in lines:
        text = " ".join(line.text.split())
        if is_bullet(line.text):
            paragraphs.append(BULLET_RE.sub("", line.text).strip())
        elif paragraphs and text:
            paragraphs[-1] = f"{paragraphs[-1]} {text}"
        elif text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def parse_summary(lines: list[Line], header: list[Line]) -> str:
    """The Summary section; without one, the paragraph above the first heading
    (from its first sentence-like line: name and contact lines are shorter)."""
    if lines:
        return join_lines(lines)
    for index, line in enumerate(header):
        if len(line.text) >= 80 and "@" not in line.text:
            return join_lines(header[index:])
    return ""


# --- Work history ---------------------------------------------------------------------------------


def is_header_line(line: Line) -> bool:
    """Could this line hold a job title, employer or location?"""
    text = line.text.strip()
    return (
        bool(text)
        and not is_bullet(text)
        and len(text) <= 90
        and not text.endswith(".")
        and not text[0].islower()  # a wrapped bullet, not a title or employer
        and find_range(text) is None
    )


def parse_work(lines: list[Line]) -> list[WorkEntry]:
    """One position per date range ("Jan 2020 – Present").

    The title, employer and location come from the date range's own line and
    up to two short lines above it (or, failing that, the line below it).
    The lines after it, up to the next position, are its description.
    """
    anchors = [
        (i, found)
        for i, line in enumerate(lines)
        if not is_bullet(line.text) and (found := find_range(line.text))
    ]
    header_starts: list[int] = []
    for k, (i, _) in enumerate(anchors):
        lowest = anchors[k - 1][0] + 1 if k else 0
        start = i
        while (
            start - 1 >= lowest
            and i - (start - 1) <= 2
            and is_header_line(lines[start - 1])
        ):
            start -= 1
        header_starts.append(start)

    entries: list[WorkEntry] = []
    for k, (i, found) in enumerate(anchors):
        end = header_starts[k + 1] if k + 1 < len(anchors) else len(lines)
        head = [line.text for line in lines[header_starts[k] : i]]
        rest = remove_span(lines[i].text, found.span)
        if rest:
            head.append(rest)
        body = lines[i + 1 : end]
        if len(fragments_of(head)) < 2 and body and is_header_line(body[0]):
            head.append(body[0].text)
            body = body[1:]
        entries.append(work_entry(head, found, body))
    return entries


def fragments_of(parts: list[str]) -> list[str]:
    fragments: list[str] = []
    for part in parts:
        for fragment in FRAGMENT_SEPARATORS_RE.split(part):
            fragment = tidy(fragment)
            if fragment:
                fragments.append(fragment)
    return fragments


def split_location(parts: list[str]) -> tuple[list[str], str]:
    """Take a location ("Austin, TX", "Remote") off the end of a header part."""
    location = ""
    remaining: list[str] = []
    for part in parts:
        part = part.replace("(", " ").replace(")", " ").strip()
        match = LOCATION_RE.search(part) if not location else None
        if match:
            location = match.group("location").strip()
            part = part[: match.start()]
        part = tidy(part)
        if part:
            remaining.append(part)
    return remaining, location


def title_score(text: str) -> int:
    return (2 if ROLE_RE.search(text) else 0) + (1 if SENIORITY_RE.search(text) else 0)


def employer_score(text: str) -> int:
    if LEGAL_SUFFIX_RE.search(text):
        return 3
    if ORG_WORD_RE.search(text) and not ROLE_RE.search(text):
        return 1
    return 0


def work_entry(head: list[str], found: DateRange, body: Sequence[Line]) -> WorkEntry:
    parts, location = split_location(head)
    fragments = fragments_of(parts)
    # "Senior Engineer, Acme Corp" with no other separator: split on the comma.
    if len(fragments) == 1 and "," in fragments[0]:
        fragments = [tidy(piece) for piece in fragments[0].split(",") if tidy(piece)]
    title = max(fragments, key=title_score, default="")
    if title and title_score(title) == 0:
        title = ""
    career_break = False
    if not title:
        title = next((f for f in fragments if CAREER_BREAK_RE.search(f)), "")
        career_break = bool(title)
    others = [fragment for fragment in fragments if fragment != title]
    employer = max(others, key=employer_score, default="")
    if employer and employer_score(employer) == 0:
        employer = ""
    leftovers = [fragment for fragment in others if fragment != employer]
    title_guessed = False
    if not title and leftovers:
        title, title_guessed = leftovers.pop(0), True
    employer_guessed = False
    if not employer and leftovers:
        employer_guessed = title_guessed or len(leftovers) > 1
        employer = leftovers.pop(0)
    return WorkEntry(
        title=title[:200],
        employer=employer[:200],
        location=location[:200],
        start_date=found.start,
        end_date=found.end,
        description=bullet_list(body),
        # A career break needs no employer; a job without one probably lost it.
        uncertain=title_guessed
        or employer_guessed
        or not title
        or (not employer and not career_break),
    )


# --- Education ---------------------------------------------------------------------------------------


def split_degree(text: str) -> tuple[str, str]:
    """ "Bachelor of Science in Computer Science" -> ("Bachelor of Science", "Computer Science")."""
    parts = re.split(r"\s+in\s+|,\s+|\s+[-–—]\s+", text, maxsplit=1)
    if len(parts) == 2:
        return tidy(parts[0]), tidy(parts[1])
    abbreviation = DEGREE_ABBREVIATION_RE.match(text)
    if abbreviation and abbreviation.end() < len(text):
        return tidy(text[: abbreviation.end()]), tidy(text[abbreviation.end() :])
    return tidy(text), ""


def is_degree(text: str) -> bool:
    return bool(DEGREE_WORDS_RE.search(text) or DEGREE_ABBREVIATION_RE.search(text))


def parse_education(lines: list[Line]) -> list[EducationEntry]:
    """Schools and degrees. A line naming a school (University, College...)
    or a degree (Bachelor, B.S., MBA...) starts a new entry when the current
    one already has one; dates go to the current entry; bullets and other
    lines (GPA, honors) are its details."""
    entries: list[EducationEntry] = []
    details: dict[int, list[Line]] = {}

    def current() -> EducationEntry:
        if not entries:
            entries.append(EducationEntry())
        return entries[-1]

    for line in lines:
        text = line.text
        if is_bullet(text):
            details.setdefault(len(entries) - 1, []).append(line)
            continue
        # Dates are taken out first, and given to the entry the rest of the
        # line belongs to (which may be a new one).
        start_date: date | None = None
        end_date: date | None = None
        in_progress = PENDING_RE.search(text) is not None  # "Expected May 2026"
        found = find_range(text)
        if found:
            start_date, end_date = found.start, found.end
            in_progress = in_progress or found.end is None  # "2022 – Present"
            text = remove_span(text, found.span)
        else:
            dates = find_dates(text)
            if dates:
                end_date = dates[-1].value  # a single date is when it ended
                text = remove_spans(text, [found_date.span for found_date in dates])
        if in_progress:
            text = tidy(PENDING_RE.sub(" ", text))
        entries_before = len(entries)
        unplaced: list[str] = []
        for fragment in fragments_of(re.split(r",\s+(?=[A-Z])", text)):
            if INSTITUTION_RE.search(fragment) and not is_degree(fragment):
                if current().institution:
                    entries.append(EducationEntry())
                current().institution = fragment[:200]
            elif is_degree(fragment):
                if current().degree:
                    entries.append(EducationEntry())
                degree, field_of_study = split_degree(fragment)
                current().degree, current().field_of_study = (
                    degree[:200],
                    field_of_study[:200],
                )
            elif (
                current().degree
                and not current().field_of_study
                and len(fragment) <= 60
                and not LOCATION_RE.search(fragment)
            ):
                current().field_of_study = fragment[:200]
            else:
                unplaced.append(fragment)
        if start_date or end_date or in_progress:
            entry = current()
            if (entry.start_date or entry.end_date) and len(entries) == entries_before:
                entry = EducationEntry()  # dates for a school not named yet
                entries.append(entry)
            entry.start_date = start_date or entry.start_date
            entry.end_date = end_date or entry.end_date
            entry.in_progress = entry.in_progress or in_progress
        if unplaced and not LOCATION_RE.search(", ".join(unplaced)):
            details.setdefault(len(entries) - 1, []).append(Line(", ".join(unplaced)))

    results: list[EducationEntry] = []
    for index, entry in enumerate(entries):
        if not entry.institution and not entry.degree:
            continue
        entry.description = join_lines(details.get(index, []))
        entry.uncertain = not entry.institution
        results.append(entry)
    return results


# --- Certifications ------------------------------------------------------------------------------------


def known_issuer(text: str) -> str:
    match = ISSUER_RE.search(text)
    return ISSUERS[match.group().lower()] if match else ""


def is_issuer_line(text: str) -> bool:
    """Is this line just an issuing organization, like "Amazon Web Services"?"""
    if ISSUER_RE.fullmatch(text):
        return True
    return (
        len(text) <= 60
        and employer_score(text) > 0
        and title_score(text) == 0
        and not CERTIFICATION_WORDS_RE.search(text)
    )


def issuer_from_brackets(text: str) -> str:
    """Bracketed text that names an issuer: "(CNCF)" or "(Amazon Web Services)",
    but not an abbreviation of the certification, like "(CKA)"."""
    if known_issuer(text) or len(text.split()) >= 2:
        return text
    return ""


def parse_certifications(lines: list[Line]) -> list[CertificationEntry]:
    """One certification per line. Lines that are just an issuer, dates or a
    credential ID belong to the certification above them.

    An "expected" date marks the certification as in progress, with that
    date as the expected completion. Renewal dates ("Recertified 2026") are
    ignored, keeping the original issue date.
    """
    entries: list[CertificationEntry] = []
    for line in lines:
        text = BULLET_RE.sub("", line.text).strip()
        if not text:
            continue
        pending = PENDING_RE.search(text) is not None
        renewal = RENEWAL_RE.search(text) is not None
        credential_id = ""
        id_match = CREDENTIAL_ID_RE.search(text)
        if id_match:
            credential_id = id_match.group("id")
            text = remove_span(text, id_match.span())
        issued: date | None = None
        expires: date | None = None
        found_range = find_range(text)
        if found_range:
            issued, expires = found_range.start, found_range.end
            text = remove_span(text, found_range.span)
        else:
            dates = find_dates(text)
            for found_date in dates:
                start = found_date.span[0]
                if EXPIRES_RE.search(text[max(0, start - 25) : start]):
                    expires = found_date.value
                else:
                    issued = issued or found_date.value
            if dates:
                text = remove_spans(text, [found_date.span for found_date in dates])
                text = tidy(EXPIRES_RE.sub(" ", ISSUED_WORDS_RE.sub(" ", text)))
        if renewal:
            issued = None
        if pending or renewal:
            text = tidy(RENEWAL_RE.sub(" ", PENDING_RE.sub(" ", text)))

        previous = entries[-1] if entries else None
        if previous is not None and (not text or is_issuer_line(text)):
            if text:
                previous.issuer = (
                    known_issuer(text) if ISSUER_RE.fullmatch(text) else text
                )[:200]
            previous.issued_on = previous.issued_on or issued
            previous.expires_on = previous.expires_on or expires
            previous.credential_id = previous.credential_id or credential_id
            previous.in_progress = previous.in_progress or pending
            continue
        if not text:
            continue
        name, issuer = text, ""
        bracketed = re.search(r"\(([^)]+)\)\s*$", name)
        if bracketed and issuer_from_brackets(bracketed.group(1).strip()):
            issuer, name = bracketed.group(1).strip(), name[: bracketed.start()].strip()
        elif not bracketed:
            fragments = [
                tidy(f)
                for f in re.split(r"\s+[|·•—]\s+|,\s+|\s+by\s+", name)
                if tidy(f)
            ]
            if len(fragments) > 1:
                name, issuer = fragments[0], fragments[1]
        entries.append(
            CertificationEntry(
                name=name[:200],
                issuer=(issuer or known_issuer(name))[:200],
                issued_on=issued,
                expires_on=expires,
                credential_id=credential_id[:200],
                uncertain=len(name) < 3,
                in_progress=pending,
            )
        )
    return entries


# --- Skills ---------------------------------------------------------------------------------------------


def skill_pattern(name: str, exact_case: bool) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![\w+#]){re.escape(name)}(?![\w+#]|\.\w)",
        0 if exact_case else re.IGNORECASE,
    )


def match_skills(
    lines: list[Line], skills_lines: list[Line], skills: Sequence[SkillOption]
) -> list[str]:
    """The shared skills the resume mentions, by ID, in the order of `skills`.

    Every skill name (and its aliases) is searched for across the whole
    resume. Names that are everyday words ("Go", "Swift") only count in the
    skills section, with their exact capitalization. Items in the skills
    section are also fuzzy-matched, to catch small spelling differences.
    """
    everything = "\n".join(line.text for line in lines)
    skills_text = "\n".join(line.text for line in skills_lines)
    matched: list[str] = []
    for skill in skills:
        if skill.name in AMBIGUOUS_SKILLS:
            found = skill_pattern(skill.name, exact_case=True).search(skills_text)
        else:
            found = skill_pattern(skill.name, exact_case=False).search(everything)
        aliases = SKILL_ALIASES.get(skill.name, ())
        if found or any(
            skill_pattern(alias, exact_case=False).search(everything)
            for alias in aliases
        ):
            matched.append(skill.id)

    # Everyday-word skills are left out: they must match exactly (above).
    fuzzy_skills = [skill for skill in skills if skill.name not in AMBIGUOUS_SKILLS]
    names = [skill.name.lower() for skill in fuzzy_skills]
    for item in SKILL_ITEM_SPLIT_RE.split(BULLET_RE.sub("", skills_text)):
        item = re.sub(r"\(.*?\)", "", item).strip(" .:-").lower()
        if not item or len(item) > 40:
            continue
        match = process.extractOne(
            item, names, scorer=fuzz.ratio, score_cutoff=SKILL_FUZZY_MIN_SCORE
        )
        if match is not None:
            skill_id = fuzzy_skills[match[2]].id
            if skill_id not in matched:
                matched.append(skill_id)
    order = {skill.id: index for index, skill in enumerate(skills)}
    return sorted(matched, key=order.__getitem__)
