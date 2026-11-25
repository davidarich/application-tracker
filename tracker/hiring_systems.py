"""Which hiring system (applicant tracking system) a job posting link belongs to.

Detection uses the link alone. The links each system is recognised by:

    Workday          <company>.wd1-wd12.myworkdayjobs.com (any myworkdayjobs.com link)
    Greenhouse       boards.greenhouse.io, job-boards.greenhouse.io, their EU
                     boards (boards.eu., job-boards.eu.), or ?gh_jid=
    Lever            jobs.lever.co/<company>/..., or jobs.eu.lever.co
    Ashby            jobs.ashbyhq.com/<company>/..., or ?ashby_jid=
    SmartRecruiters  jobs.smartrecruiters.com or careers.smartrecruiters.com
    iCIMS            careers-<company>.icims.com, or icims.com/jobs
    Comeet           comeet.com/jobs/<company>/... or comeet.co/jobs/...
    Spark Hire       sparkhire.com (its one-way video interviews)
    Workable         apply.workable.com/<company>/..., or the older
                     <company>.workable.com/j/... and /jobs/...
    BambooHR         <company>.bamboohr.com
    Teamtailor       <company>.teamtailor.com
    Jobvite          jobs.jobvite.com, careers.jobvite.com or app.jobvite.com
    Oracle Taleo     <company>.taleo.net
    SuccessFactors   successfactors.com or .eu, career*.sapsf.com, or jobs.sap.com
    Recruitee        <company>.recruitee.com
    Personio         <company>.jobs.personio.de or .com, or a job page
                     (/job/...) on <company>.personio.de or .com
    Breezy HR        <company>.breezy.hr
    JazzHR           <company>.applytojob.com

A vendor's own website (greenhouse.io/blog, www.icims.com/products) isn't a
job posting, so it isn't recognised. Neither is LinkedIn Easy Apply (it's a
button on LinkedIn, not a link), a company's own careers site without a
tracking code (?gh_jid=, ?ashby_jid=), or a branded Teamtailor site.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit


@dataclass(frozen=True)
class Link:
    """The parts of a link detection looks at, lowercased (except the path)."""

    host: str  # without "www."
    path: str
    parameters: frozenset[str]  # query parameter names, lowercased


@dataclass(frozen=True)
class HiringSystem:
    key: str
    name: str
    matches: Callable[[Link], bool]


def on(host: str, domain: str) -> bool:
    """Whether `host` is `domain` or one of its subdomains."""
    return host == domain or host.endswith("." + domain)


def subdomain_of(host: str, domain: str) -> bool:
    """Whether `host` is a subdomain of `domain` (a company's own, e.g. acme.bamboohr.com)."""
    return host.endswith("." + domain)


WORKDAY_RE = re.compile(r"^[a-z0-9-]+\.wd(?:[1-9]|1[0-2])\.myworkdayjobs\.com$")
ICIMS_RE = re.compile(r"^careers-[a-z0-9-]+\.icims\.com$")
SAPSF_RE = re.compile(r"^career[a-z0-9-]*\.sapsf\.com$")
GREENHOUSE_BOARDS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.eu.greenhouse.io",
    }
)
LEVER_BOARDS = frozenset({"jobs.lever.co", "jobs.eu.lever.co"})
SMARTRECRUITERS_BOARDS = frozenset(
    {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}
)
JOBVITE_BOARDS = frozenset(
    {"jobs.jobvite.com", "careers.jobvite.com", "app.jobvite.com"}
)

# In the order they're tried. Hosts come first and tracking codes last: a
# Greenhouse code on an Ashby board is still an Ashby page.
HIRING_SYSTEMS: tuple[HiringSystem, ...] = (
    HiringSystem(
        "workday",
        "Workday",
        lambda link: (
            bool(WORKDAY_RE.match(link.host)) or on(link.host, "myworkdayjobs.com")
        ),
    ),
    HiringSystem(
        "greenhouse",
        "Greenhouse",
        lambda link: link.host in GREENHOUSE_BOARDS,
    ),
    HiringSystem("lever", "Lever", lambda link: link.host in LEVER_BOARDS),
    HiringSystem("ashby", "Ashby", lambda link: link.host == "jobs.ashbyhq.com"),
    HiringSystem(
        "smartrecruiters",
        "SmartRecruiters",
        lambda link: link.host in SMARTRECRUITERS_BOARDS,
    ),
    HiringSystem(
        "icims",
        "iCIMS",
        lambda link: (
            bool(ICIMS_RE.match(link.host))
            or (on(link.host, "icims.com") and link.path.startswith("/jobs"))
        ),
    ),
    HiringSystem(
        "comeet",
        "Comeet",
        lambda link: (
            (on(link.host, "comeet.com") or on(link.host, "comeet.co"))
            and link.path.startswith("/jobs/")
        ),
    ),
    HiringSystem(
        "spark_hire", "Spark Hire", lambda link: on(link.host, "sparkhire.com")
    ),
    HiringSystem(
        "workable",
        "Workable",
        lambda link: (
            link.host == "apply.workable.com"
            or (
                subdomain_of(link.host, "workable.com")
                and link.path.startswith(("/j/", "/jobs/"))
            )
        ),
    ),
    HiringSystem(
        "bamboohr", "BambooHR", lambda link: subdomain_of(link.host, "bamboohr.com")
    ),
    HiringSystem(
        "teamtailor",
        "Teamtailor",
        lambda link: subdomain_of(link.host, "teamtailor.com"),
    ),
    HiringSystem("jobvite", "Jobvite", lambda link: link.host in JOBVITE_BOARDS),
    HiringSystem(
        "taleo", "Oracle Taleo", lambda link: subdomain_of(link.host, "taleo.net")
    ),
    HiringSystem(
        "successfactors",
        "SAP SuccessFactors",
        lambda link: (
            on(link.host, "successfactors.com")
            or on(link.host, "successfactors.eu")
            or bool(SAPSF_RE.match(link.host))
            or link.host == "jobs.sap.com"
        ),
    ),
    HiringSystem(
        "recruitee", "Recruitee", lambda link: subdomain_of(link.host, "recruitee.com")
    ),
    HiringSystem(
        "personio",
        "Personio",
        lambda link: any(
            subdomain_of(link.host, "jobs." + domain)
            or (subdomain_of(link.host, domain) and link.path.startswith("/job/"))
            for domain in ("personio.de", "personio.com")
        ),
    ),
    HiringSystem(
        "breezy", "Breezy HR", lambda link: subdomain_of(link.host, "breezy.hr")
    ),
    HiringSystem(
        "jazzhr", "JazzHR", lambda link: subdomain_of(link.host, "applytojob.com")
    ),
    # Tracking codes left on a company's own careers site.
    HiringSystem("greenhouse", "Greenhouse", lambda link: "gh_jid" in link.parameters),
    HiringSystem("ashby", "Ashby", lambda link: "ashby_jid" in link.parameters),
)


def parse_link(url: str) -> Link | None:
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    parameters = frozenset(
        name.lower() for name, _ in parse_qsl(parts.query, keep_blank_values=True)
    )
    return Link(host=host.removeprefix("www."), path=parts.path, parameters=parameters)


def detect_hiring_system(url: str) -> HiringSystem | None:
    """The hiring system a posting link belongs to, or None if it isn't recognised."""
    link = parse_link(url)
    if link is None:
        return None
    return next((system for system in HIRING_SYSTEMS if system.matches(link)), None)
