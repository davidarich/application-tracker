"""Cleaning job posting links before they're saved (by the job form and the API).

Links copied from job boards, emails and ads carry tracking parameters
(utm_source, gclid, ...) that say how you got there, not which job it is. They
make the same posting look like different links, so they're removed. Anything
else is kept, because some hiring systems need their query parameters to show
the job (for example Taleo's ?job=, SuccessFactors' ?company= or Greenhouse's
embed ?for=&token=).

The rules, in order, for each parameter name (ignoring case):

1. utm_* (any UTM parameter, utm_id included): removed.
2. A known tracking parameter (TRACKING_PARAMETERS, TRACKING_PREFIXES): removed.
   Some of these end in "id" (gclid, fbclid, li_fat_id) but identify an ad
   click, not the job.
3. Anything resembling an ID (looks_like_id): kept, just in case.
4. A known referral or source parameter (SOURCE_PARAMETERS): removed.
5. Anything else: kept.

Kept parameters are copied exactly as written (not re-encoded), in order. The
host is lowercased, and the fragment (#...) is kept, since some careers sites
route to the job with it.
"""

import re
from typing import cast
from urllib.parse import SplitResult, unquote_plus, urlsplit, urlunsplit

# Ad, email and analytics click identifiers.
TRACKING_PARAMETERS = frozenset(
    {
        "gclid",  # Google Ads
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",
        "_gl",  # Google Analytics cross-domain linker
        "_ga",
        "fbclid",  # Meta
        "msclkid",  # Microsoft Ads
        "yclid",  # Yandex
        "ttclid",  # TikTok
        "twclid",  # X (Twitter)
        "li_fat_id",  # LinkedIn Ads
        "igshid",  # Instagram
        "mc_cid",  # Mailchimp
        "mc_eid",
        "_hsenc",  # HubSpot
        "_hsmi",
        "hsctatracking",
        "mkt_tok",  # Marketo
        "oly_anon_id",  # Omeda
        "oly_enc_id",
        "vero_id",  # Vero
        "wickedid",
        "rb_clickid",
        "s_kwcid",  # Adobe
        "ef_id",
    }
)
TRACKING_PREFIXES = ("utm_", "hsa_", "pk_", "mtm_", "matomo_")

# How you reached the posting: job board names, referrers, "source" fields.
SOURCE_PARAMETERS = frozenset(
    {
        "ref",
        "referer",
        "referrer",
        "ref_src",
        "ref_url",
        "src",
        "source",
        "sourcetype",
        "source_type",
        "gh_src",  # Greenhouse
        "lever-source",  # Lever
        "lever-origin",
        "__jvst",  # Jobvite
        "__jvsd",
        "iis",  # iCIMS
        "iisn",
        "trk",  # LinkedIn
        "trkinfo",
        "campaign",
        "medium",
        "channel",
        "cmp",
    }
)

# Words in a parameter name that make it look like it names the job or its
# employer (job=, token=, jk= for Indeed's job key, for= for a Greenhouse board).
ID_WORDS = frozenset(
    {
        "id",
        "ids",
        "jid",
        "uuid",
        "guid",
        "key",
        "jk",
        "vjk",
        "token",
        "job",
        "jobs",
        "req",
        "requisition",
        "posting",
        "position",
        "vacancy",
        "opening",
        "code",
        "number",
        "num",
        "no",
    }
)
WORD_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def words(name: str) -> list[str]:
    """A parameter name's words, lowercased: "currentJobId" is current, job, id."""
    return [word.lower() for word in cast(list[str], WORD_RE.findall(name))]


def looks_like_id(name: str) -> bool:
    """Whether a parameter name resembles an ID: a word like id or job, or a
    word ending in "id" (jobid, gh_jid, reqid, postingid)."""
    return any(
        word in ID_WORDS or (word.endswith("id") and len(word) > 2)
        for word in words(name)
    )


def is_tracking(name: str) -> bool:
    """Whether to remove a parameter (see the module docstring for the rules)."""
    lowered = name.lower()
    if lowered.startswith(TRACKING_PREFIXES) or lowered in TRACKING_PARAMETERS:
        return True
    if looks_like_id(name):
        return False
    return lowered in SOURCE_PARAMETERS


def clean_posting_url(url: str) -> str:
    """`url` without tracking parameters, with its host lowercased; anything
    that doesn't parse as a link is returned as is (stripped)."""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme or not parts.netloc:
        return url
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and not is_tracking(unquote_plus(pair.split("=", 1)[0]))
    ]
    netloc = parts.netloc
    if parts.hostname:
        # Only the host part: user info (rare) and the port are kept as written.
        userinfo, at, hostport = netloc.rpartition("@")
        netloc = userinfo + at + hostport.lower()
    cleaned = SplitResult(
        parts.scheme.lower(), netloc, parts.path, "&".join(kept), parts.fragment
    )
    return urlunsplit(cleaned)


def posting_url_key(url: str) -> str:
    """A key for telling whether two links are the same posting, so the small
    differences between copies of a link don't matter: http or https, www.,
    letter case, a trailing slash, the order of query parameters, tracking
    parameters (removed as clean_posting_url() does) and #anchors such as
    #apply. A #/route (as some careers sites use to name the job) still
    counts. Every other query parameter counts too, since some hiring systems
    name the job with one (Taleo's ?job=, SuccessFactors' ?career_job_req_id=).

    Returns "" for anything that isn't a web link.
    """
    try:
        parts = urlsplit(clean_posting_url(url))
        host = (parts.hostname or "").lower()
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not host:
        return ""
    parameters = sorted(unquote_plus(pair) for pair in parts.query.split("&") if pair)
    route = parts.fragment if parts.fragment.startswith(("/", "!/")) else ""
    key = host.removeprefix("www.") + parts.path.rstrip("/")
    if parameters:
        key += "?" + "&".join(parameters)
    if route:
        key += "#" + route
    return key.lower()
