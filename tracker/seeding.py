"""Generate realistic mock data for development (used by `manage.py seed`).

Everything is fictional: company websites and email addresses use the reserved
.example top-level domain, and posting URLs use example.com.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import User

from .models import (
    Application,
    ApplicationStatusChange,
    Company,
    Contact,
    CoverLetter,
    Job,
    Skill,
)
from .ownership import companies_for, jobs_for

Status = Application.Status


@dataclass(frozen=True)
class SeedCompany:
    name: str
    is_staffing_agency: bool
    mission_statement: str


COMPANIES: list[SeedCompany] = [
    SeedCompany(
        "Northwind Systems",
        False,
        "We build dependable infrastructure software for teams that can't afford downtime. Our goal is to make running systems at scale feel calm, predictable and boring in the best way.",
    ),
    SeedCompany(
        "Bluefin Analytics",
        False,
        "Bluefin turns messy operational data into clear decisions. We believe every team deserves analytics they can trust without needing a data science department to read them.",
    ),
    SeedCompany(
        "Cobalt Health",
        False,
        "Our mission is to make healthcare simpler for patients and the people who care for them. We design tools that give clinicians back time and give patients clear answers.",
    ),
    SeedCompany(
        "Lumen Robotics",
        False,
        "Lumen builds safe, affordable robots for warehouses and small manufacturers. We want automation to help people do their best work, not replace the judgment they bring.",
    ),
    SeedCompany(
        "Harbor Logistics",
        False,
        "We move goods for growing businesses with honesty and precision. Harbor exists to make shipping transparent, from the first quote to the final delivery.",
    ),
    SeedCompany(
        "Quill Learning",
        False,
        "Quill helps students become confident writers. We pair thoughtful teachers with practical software so that every learner gets feedback that actually moves them forward.",
    ),
    SeedCompany(
        "Redwood Payments",
        False,
        "Redwood makes getting paid easy for independent businesses. We are building fair, transparent payment tools that put small merchants on equal footing with the giants.",
    ),
    SeedCompany(
        "Summit Cloud",
        False,
        "Summit gives developers a cloud platform that stays out of their way. We obsess over reliability, clear pricing and documentation people genuinely enjoy reading.",
    ),
    SeedCompany(
        "Vantage Media",
        False,
        "Vantage tells stories that help people understand a complicated world. We invest in careful reporting, accessible design and journalism that respects its audience.",
    ),
    SeedCompany(
        "Orchard Labs",
        False,
        "Orchard Labs is a research studio exploring how software can help communities grow food locally. We prototype boldly, share what we learn and build in the open.",
    ),
    SeedCompany(
        "Meridian Energy",
        False,
        "Meridian accelerates the shift to clean energy by making solar and storage practical for homes and towns. We measure success in kilowatt-hours that never touched a fossil fuel.",
    ),
    SeedCompany(
        "Kestrel Security",
        False,
        "Kestrel protects organizations from threats without slowing them down. We believe good security is invisible to the people it protects and obvious to the people it stops.",
    ),
    SeedCompany(
        "Juniper Bio",
        False,
        "Juniper Bio develops diagnostics that catch disease earlier and cost less. Our scientists and engineers work toward a future where a simple test can change the course of an illness.",
    ),
    SeedCompany(
        "Driftwood Software",
        False,
        "Driftwood crafts thoughtful software for small teams with big ambitions. We keep our products simple, our support personal and our roadmap shaped by the people who use it.",
    ),
    SeedCompany(
        "Copperline Data",
        False,
        "Copperline builds the pipelines that keep data flowing between the tools businesses rely on. We aim to make integration so reliable that nobody has to think about it.",
    ),
    SeedCompany(
        "Larkspur Health",
        False,
        "Larkspur brings mental health support to people where they are. We combine licensed clinicians with friendly technology to make care approachable, affordable and stigma-free.",
    ),
    SeedCompany(
        "Ironbark Systems",
        False,
        "Ironbark engineers rugged control systems for utilities and transport networks. We build for decades, not quarters, because the infrastructure we support has to last.",
    ),
    SeedCompany(
        "Saltmarsh Media",
        False,
        "Saltmarsh produces podcasts and documentaries about the natural world. We want every listener to come away more curious about, and more connected to, the places around them.",
    ),
    SeedCompany(
        "Halcyon Freight",
        False,
        "Halcyon is reinventing regional trucking with better routes, fairer pay for drivers and fewer empty miles. We think freight can be efficient and humane at the same time.",
    ),
    SeedCompany(
        "Brightwater Learning",
        False,
        "Brightwater offers practical courses that help adults change careers. We focus on skills employers actually hire for and on mentors who have done the work themselves.",
    ),
    SeedCompany(
        "Foxglove Analytics",
        False,
        "Foxglove helps retailers understand their customers without invading their privacy. We prove that useful insight and respect for personal data can go hand in hand.",
    ),
    SeedCompany(
        "Granite Peak Insurance",
        False,
        "Granite Peak makes insurance understandable. We write plain-language policies, settle claims quickly and treat every customer like a neighbor rather than a policy number.",
    ),
    SeedCompany(
        "Tidewell Energy",
        False,
        "Tidewell harnesses ocean currents to generate steady, renewable power for coastal communities. Our engineers design with the sea, not against it.",
    ),
    SeedCompany(
        "Amberfield Retail",
        False,
        "Amberfield runs neighborhood stores that stock local makers alongside everyday essentials. We want shopping close to home to be convenient, affordable and good for the community.",
    ),
    SeedCompany(
        "Hollowbrook Games",
        False,
        "Hollowbrook makes cozy, story-rich games for players of every age. We care about kindness in our worlds and in our studio, and we never crunch to ship.",
    ),
    SeedCompany(
        "Talentbridge Staffing",
        True,
        "Talentbridge connects skilled professionals with companies that value them. We listen first, match carefully and stay in touch long after the offer is signed.",
    ),
    SeedCompany(
        "Apex Recruiting Partners",
        True,
        "Apex places senior engineering and product leaders with fast-growing companies. Our recruiters are former practitioners who understand the roles they fill.",
    ),
    SeedCompany(
        "Wrenfield Talent",
        True,
        "Wrenfield helps candidates find roles where they will thrive, not just jobs they can get. We are honest about fit and transparent about every step of the process.",
    ),
    SeedCompany(
        "Northgate Talent Group",
        True,
        "Northgate specializes in contract and contract-to-hire technology roles. We help companies scale quickly and help contractors build steady, rewarding careers.",
    ),
    SeedCompany(
        "Bramble & Birch Recruiting",
        True,
        "Bramble & Birch is a boutique agency for mission-driven nonprofits and social enterprises. We find people who care about the cause as much as the craft.",
    ),
]

TITLES = [
    "Backend Engineer",
    "Senior Backend Engineer",
    "Full-stack Developer",
    "Frontend Developer",
    "Python Developer",
    "Platform Engineer",
    "Site Reliability Engineer",
    "DevOps Engineer",
    "Data Engineer",
    "Staff Data Engineer",
    "Machine Learning Engineer",
    "Engineering Manager",
    "Solutions Architect",
    "Mobile Developer",
    "Security Engineer",
]


@dataclass(frozen=True)
class SeedSkill:
    name: str
    description: str


# Shared skills (not owned by any user), in four groups. Each seeded job gets
# some from every group: see pick_skills().
SKILL_LANGUAGES: list[SeedSkill] = [
    SeedSkill(
        "Python",
        "General-purpose language popular for web back ends, data and automation.",
    ),
    SeedSkill(
        "JavaScript",
        "The language of the web browser, also used on servers with Node.js.",
    ),
    SeedSkill(
        "TypeScript",
        "JavaScript with static types, for larger and safer front-end and Node.js code.",
    ),
    SeedSkill(
        "Go",
        "Compiled language with simple concurrency, common for cloud services and tooling.",
    ),
    SeedSkill(
        "Java", "Long-established language for enterprise back ends and Android."
    ),
    SeedSkill(
        "C#", "Microsoft's main language for .NET services, desktop apps and games."
    ),
    SeedSkill("Rust", "Systems language focused on memory safety and performance."),
    SeedSkill(
        "Kotlin", "Modern JVM language used for Android and server-side development."
    ),
    SeedSkill("Ruby", "Expressive scripting language best known for Ruby on Rails."),
    SeedSkill("SQL", "The standard language for querying and shaping relational data."),
]

SKILL_FRAMEWORKS: list[SeedSkill] = [
    SeedSkill(
        "Django", "Batteries-included Python web framework with an ORM and admin."
    ),
    SeedSkill("FastAPI", "Python framework for building typed, high-performance APIs."),
    SeedSkill("Flask", "Lightweight Python web framework for small services and APIs."),
    SeedSkill(
        "React", "Component-based JavaScript library for building user interfaces."
    ),
    SeedSkill(
        "Vue.js", "Progressive JavaScript framework for building web interfaces."
    ),
    SeedSkill("Angular", "TypeScript framework for large single-page applications."),
    SeedSkill("Next.js", "React framework with server rendering and routing built in."),
    SeedSkill(
        "Spring Boot", "Opinionated Java framework for production-ready services."
    ),
    SeedSkill(
        ".NET", "Microsoft's cross-platform framework for web, cloud and desktop apps."
    ),
    SeedSkill("Ruby on Rails", "Convention-over-configuration web framework for Ruby."),
]

SKILL_DEVOPS: list[SeedSkill] = [
    SeedSkill(
        "Docker", "Packaging applications and their dependencies into containers."
    ),
    SeedSkill(
        "Kubernetes",
        "Orchestrating and scaling containers across clusters of machines.",
    ),
    SeedSkill("Terraform", "Defining and provisioning infrastructure as code."),
    SeedSkill("Ansible", "Agentless configuration management and automation."),
    SeedSkill("GitHub Actions", "CI/CD workflows that run from a GitHub repository."),
    SeedSkill("Jenkins", "Self-hosted automation server for builds and deployments."),
    SeedSkill("Helm", "Package manager for deploying applications to Kubernetes."),
    SeedSkill(
        "Prometheus", "Collecting and querying time-series metrics for monitoring."
    ),
    SeedSkill("Grafana", "Dashboards and alerting on top of metrics and logs."),
    SeedSkill("Argo CD", "GitOps continuous delivery for Kubernetes."),
]

SKILL_CLOUD: list[SeedSkill] = [
    SeedSkill(
        "AWS Lambda",
        "Running code on AWS without managing servers (serverless functions).",
    ),
    SeedSkill("Amazon S3", "Durable object storage on AWS."),
    SeedSkill("Amazon EC2", "Resizable virtual machines on AWS."),
    SeedSkill("Amazon RDS", "Managed relational databases on AWS."),
    SeedSkill(
        "Amazon DynamoDB", "Fully managed NoSQL key-value and document database on AWS."
    ),
    SeedSkill("Azure Functions", "Serverless functions on Microsoft Azure."),
    SeedSkill(
        "Azure Kubernetes Service", "Managed Kubernetes clusters on Microsoft Azure."
    ),
    SeedSkill(
        "Azure Blob Storage", "Object storage for unstructured data on Microsoft Azure."
    ),
    SeedSkill("Google Cloud Run", "Running containers serverlessly on Google Cloud."),
    SeedSkill(
        "Google BigQuery", "Serverless data warehouse for analytics on Google Cloud."
    ),
]

SKILL_GROUPS: list[tuple[list[SeedSkill], int, int]] = [
    # (skills, fewest, most) to give each job from the group
    (SKILL_LANGUAGES, 1, 2),
    (SKILL_FRAMEWORKS, 1, 2),
    (SKILL_DEVOPS, 1, 2),
    (SKILL_CLOUD, 0, 2),
]
SEED_SKILLS: list[SeedSkill] = [
    skill for skills, _, _ in SKILL_GROUPS for skill in skills
]

# (city, state / region)
CITIES: list[tuple[str, str]] = [
    ("New York", "NY"),
    ("Austin", "TX"),
    ("Seattle", "WA"),
    ("San Francisco", "CA"),
    ("Denver", "CO"),
    ("Boston", "MA"),
    ("Chicago", "IL"),
    ("Toronto", "ON"),
    ("London", "UK"),
    ("Berlin", "Germany"),
]
# Workplace types and their relative frequency; "" means the posting doesn't say.
WORKPLACE_WEIGHTS: list[tuple[str, int]] = [
    (Job.WorkplaceType.IN_OFFICE.value, 3),
    (Job.WorkplaceType.HYBRID.value, 4),
    (Job.WorkplaceType.REMOTE.value, 4),
    ("", 1),
]
REMOTE_WITHOUT_CITY = 0.6  # share of remote jobs that list no city

FIRST_NAMES = [
    "Alex",
    "Sam",
    "Jordan",
    "Priya",
    "Mateo",
    "Chen",
    "Amara",
    "Noah",
    "Lena",
    "Omar",
]
LAST_NAMES = [
    "Rivera",
    "Patel",
    "Nguyen",
    "Okafor",
    "Schmidt",
    "Kowalski",
    "Haddad",
    "Kim",
    "Silva",
]

# Chance an application moves on to each next stage; otherwise it may close.
NEXT_STAGES: list[tuple[Application.Status, float]] = [
    (Status.RESPONDED, 0.6),
    (Status.INTERVIEWING, 0.6),
    (Status.OFFER, 0.4),
]
CLOSE_WHEN_STUCK = 0.6  # chance a stalled application is closed (rejected/withdrawn)
CLOSE_AFTER_OFFER = 0.3  # chance an offer is then closed (declined/accepted elsewhere)
IGNORE_RATE = 0.12  # share of jobs the user decides not to pursue (Ignored)
APPLY_RATE = 0.7  # share of jobs that get an application
COVER_LETTER_RATE = 0.4  # share of applications with a cover letter


@dataclass(frozen=True)
class SeedResult:
    companies: int
    contacts: int
    jobs: int
    applications: int
    status_changes: int
    cover_letters: int
    skills: int  # new skills created (shared, so only the first run adds them)
    jobs_given_skills: int  # the user's existing jobs that had no skills
    deleted_samples: int  # soft-deleted examples added (company, job, skill)


def clear_tracker_data(user: User) -> None:
    """Delete `user`'s companies and everything that hangs off them (contacts,
    jobs, applications, status history, cover letters). Other users' data and
    uploaded files are kept. Soft-deleted companies are removed too."""
    _ = Company.objects.filter(user_owner=user).delete()


def ensure_skills() -> tuple[dict[str, Skill], int]:
    """Create any SEED_SKILLS that don't exist yet (matching names ignoring
    case). Return the seed skills by name, and how many were created."""
    existing = {skill.name.lower(): skill for skill in Skill.objects.all()}
    new = [
        Skill(name=seed_skill.name, description=seed_skill.description)
        for seed_skill in SEED_SKILLS
        if seed_skill.name.lower() not in existing
    ]
    _ = Skill.objects.bulk_create(new)
    for skill in new:
        existing[skill.name.lower()] = skill
    # Seed skills someone (soft) deleted stay deleted: they aren't picked.
    active = {
        s.name: existing[s.name.lower()]
        for s in SEED_SKILLS
        if not existing[s.name.lower()].is_deleted
    }
    return active, len(new)


# Soft-deleted examples, so hidden records exist while developing. Each is
# added once: the skill once overall (skills are shared), the company (with a
# job, hidden because its company is) and the job once per user.
DELETED_SKILL = SeedSkill("Perl", "Scripting language known for text processing.")
DELETED_COMPANY = SeedCompany(
    "Closed Door Ventures",
    False,
    "We were building a marketplace for shared office space before winding down.",
)
DELETED_COMPANY_JOB_TITLE = "Founding Engineer"
DELETED_JOB_TITLE = "Data Analyst (posting withdrawn)"


def add_deleted_samples(user: User, companies: list[Company]) -> int:
    """Add the soft-deleted examples that don't exist yet; return how many."""
    added = 0
    if not Skill.objects.filter(name__iexact=DELETED_SKILL.name).exists():
        _ = Skill.objects.create(
            name=DELETED_SKILL.name,
            description=DELETED_SKILL.description,
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        added += 1
    owned = Company.objects.filter(user_owner=user)
    if not owned.filter(name__iexact=DELETED_COMPANY.name).exists():
        company = Company.objects.create(
            user_owner=user,
            name=DELETED_COMPANY.name,
            website=f"https://{slugify(DELETED_COMPANY.name)}.example",
            mission_statement=DELETED_COMPANY.mission_statement,
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        _ = Job.objects.create(company=company, title=DELETED_COMPANY_JOB_TITLE)
        added += 1
    owned_jobs = Job.objects.filter(company__user_owner=user)
    if companies and not owned_jobs.filter(title=DELETED_JOB_TITLE).exists():
        _ = Job.objects.create(
            company=companies[0],
            title=DELETED_JOB_TITLE,
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        added += 1
    return added


def pick_skills(rng: random.Random, skills: dict[str, Skill]) -> list[Skill]:
    """A plausible mix for one job: a few from each SKILL_GROUPS group."""
    picked: list[Skill] = []
    for group, fewest, most in SKILL_GROUPS:
        available = [seed_skill for seed_skill in group if seed_skill.name in skills]
        count = min(rng.randint(fewest, most), len(available))
        for seed_skill in rng.sample(available, count):
            picked.append(skills[seed_skill.name])
    return picked


def plan_history(
    applied_at: datetime, now: datetime, rng: random.Random
) -> list[tuple[Application.Status, datetime]]:
    """A plausible sequence of (status, when) for one application, ending by `now`."""
    history: list[tuple[Application.Status, datetime]] = [(Status.APPLIED, applied_at)]
    moment = applied_at

    def step() -> datetime | None:
        later = moment + timedelta(days=rng.uniform(1, 6), hours=rng.uniform(0, 8))
        return later if later <= now else None

    for status, chance in NEXT_STAGES:
        later = step()
        if later is None:
            return history
        if rng.random() < chance:
            moment = later
            history.append((status, moment))
        else:
            if rng.random() < CLOSE_WHEN_STUCK:
                history.append((Status.CLOSED, later))
            return history

    later = step()
    if later is not None and rng.random() < CLOSE_AFTER_OFFER:
        history.append((Status.CLOSED, later))
    return history


@transaction.atomic
def add_missing_contacts(companies: list[Company], rng: random.Random) -> list[Contact]:
    """Give each of `companies` that has no contacts one or two; return them.

    Companies that already have contacts are left alone, so seeding again
    only fills the gaps.
    """
    contacts: list[Contact] = []
    empty = Company.objects.filter(
        id__in=[company.id for company in companies], contacts__isnull=True
    )
    for company in empty.order_by("name"):
        for _ in range(rng.randint(1, 2)):
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            contacts.append(
                Contact(
                    company=company,
                    name=f"{first} {last}",
                    email=f"{first}.{last}@{slugify(company.name)}.example".lower(),
                    phone_number=f"555-01{rng.randint(0, 99):02}",
                )
            )
    return Contact.objects.bulk_create(contacts)


def seed(
    *,
    user: User,
    jobs: int,
    days: int,
    rng: random.Random,
    now: datetime | None = None,
) -> SeedResult:
    """Create `jobs` jobs for `user` (with companies, contacts, applications,
    status history, cover letters and skills) spread over the last `days` days.

    Seed companies the user already has are reused, and any without contacts
    are given some.

    The shared seed skills are created first if they don't exist yet, and the
    user's existing jobs that have no skills are given some.
    """
    now = now or timezone.now()
    skills, new_skills = ensure_skills()

    # Jobs seeded before skills existed (or added without any) get a mix too.
    # Jobs that already have skills are left alone.
    jobs_without_skills = list(jobs_for(user).filter(skills__isnull=True))
    for job in jobs_without_skills:
        job.skills.set(pick_skills(rng, skills))

    def moment_in_window() -> datetime:
        return now - timedelta(days=rng.uniform(0, days))

    # Companies: reuse the user's existing ones by name, so seeding twice
    # doesn't fail on the per-user, case-insensitive unique name constraint.
    companies: list[Company] = []
    new_companies: list[Company] = []
    for seed_company in COMPANIES:
        name = seed_company.name
        company = companies_for(user).filter(name__iexact=name).first()
        if company is None:
            company = Company.objects.create(
                user_owner=user,
                name=name,
                website=f"https://{slugify(name)}.example",
                is_staffing_agency=seed_company.is_staffing_agency,
                mission_statement=seed_company.mission_statement,
            )
            company.date_added = now - timedelta(days=days + rng.uniform(1, 10))
            new_companies.append(company)
        companies.append(company)
    _ = Company.objects.bulk_update(new_companies, ["date_added"])

    contacts = add_missing_contacts(companies, rng)

    job_rows: list[Job] = []
    job_dates: list[datetime] = []
    application_rows: list[Application] = []
    application_dates: list[tuple[datetime, datetime]] = []  # (created, updated)
    change_rows: list[ApplicationStatusChange] = []
    letter_rows: list[CoverLetter] = []
    for _ in range(jobs):
        company = rng.choice(companies)
        title = rng.choice(TITLES)
        salary_min: int | None = None
        salary_max: int | None = None
        if rng.random() < 0.7:
            salary_min = rng.randrange(80, 181, 5) * 1000
            salary_max = salary_min + rng.randrange(10, 51, 5) * 1000
        workplace_type = rng.choices(
            [value for value, _ in WORKPLACE_WEIGHTS],
            weights=[weight for _, weight in WORKPLACE_WEIGHTS],
        )[0]
        city, state = rng.choice(CITIES)
        if (
            workplace_type == Job.WorkplaceType.REMOTE.value
            and rng.random() < REMOTE_WITHOUT_CITY
        ):
            city, state = "", ""
        job = Job(
            company=company,
            title=title,
            posting_url=f"https://example.com/jobs/{slugify(company.name)}-{slugify(title)}-{rng.randrange(10**5)}",
            location_city=city,
            location_state=state,
            workplace_type=workplace_type,
            description=(
                f"{company.name} is hiring a {title} to help build and run its products. "
                + "You'll work with a small team, own features end to end, and "
                + "collaborate closely with product and design."
            ),
            salary_min=salary_min,
            salary_max=salary_max,
        )
        job_rows.append(job)

        roll = rng.random()
        if roll < IGNORE_RATE:
            # Skipped without applying: one Ignored entry, a day or two after
            # the job was added.
            added_at = moment_in_window()
            ignored_at = min(added_at + timedelta(days=rng.uniform(0, 2)), now)
            job_dates.append(added_at)
            application = Application(job=job, status=Status.IGNORED)
            application_rows.append(application)
            application_dates.append((ignored_at, ignored_at))
            change_rows.append(
                ApplicationStatusChange(
                    application=application,
                    status=Status.IGNORED,
                    changed_at=ignored_at,
                )
            )
            continue
        if roll >= IGNORE_RATE + APPLY_RATE:
            job_dates.append(moment_in_window())
            continue

        applied_at = moment_in_window()
        job_dates.append(applied_at - timedelta(days=rng.uniform(0, 3)))
        history = plan_history(applied_at, now, rng)
        final_status, last_change = history[-1]
        application = Application(job=job, status=final_status)
        application_rows.append(application)
        application_dates.append((applied_at, last_change))
        change_rows.extend(
            ApplicationStatusChange(
                application=application, status=status, changed_at=when
            )
            for status, when in history
        )
        if rng.random() < COVER_LETTER_RATE:
            letter_rows.append(
                CoverLetter(
                    application=application,
                    contents=(
                        f"Dear {company.name} hiring team,\n\n"
                        + f"I'm excited to apply for the {title} role. "
                        + "I enjoy building reliable, well-tested software and "
                        + "would love to bring that to your team.\n\nBest regards"
                    ),
                )
            )

    # bulk_create skips Application.save(), so no history is auto-recorded:
    # the planned history above is written instead. Inserting stamps the
    # auto_now/auto_now_add fields with the current time (on the objects too),
    # so the backdated timestamps are set afterwards and saved with bulk_update.
    _ = Job.objects.bulk_create(job_rows)
    for job, date_added in zip(job_rows, job_dates, strict=True):
        job.date_added = date_added
    _ = Job.objects.bulk_update(job_rows, ["date_added"])
    for job in job_rows:
        job.skills.set(pick_skills(rng, skills))

    _ = Application.objects.bulk_create(application_rows)
    for application, (created, updated) in zip(
        application_rows, application_dates, strict=True
    ):
        application.created_at = created
        application.updated_at = updated
    _ = Application.objects.bulk_update(application_rows, ["created_at", "updated_at"])
    _ = ApplicationStatusChange.objects.bulk_create(change_rows)
    _ = CoverLetter.objects.bulk_create(letter_rows)

    return SeedResult(
        companies=len(new_companies),
        contacts=len(contacts),
        jobs=len(job_rows),
        applications=len(application_rows),
        status_changes=len(change_rows),
        cover_letters=len(letter_rows),
        skills=new_skills,
        jobs_given_skills=len(jobs_without_skills),
        deleted_samples=add_deleted_samples(user, companies),
    )
