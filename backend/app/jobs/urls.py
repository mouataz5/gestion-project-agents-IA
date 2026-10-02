"""Job URLs: canonical form for deduplication, ATS detection and public-URL validation.

``canonical_url`` is a comparison key, not necessarily a fetchable address: the scheme becomes
https, ``www.`` and default ports are dropped, tracking parameters and fragments are removed,
query parameters are sorted, and well-known job URLs collapse to one form (LinkedIn job views,
Indeed job keys, ATS "apply" pages).

``validate_public_url`` rejects anything that could reach a private network (SSRF): non-HTTP
schemes, embedded credentials, unusual ports, local host names and non-global IP addresses in
every notation. Fetchers (Phase 10) must also check the resolved address at connection time.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.errors import AppError
from app.jobs.types import AtsType

MAX_URL_LENGTH = 2048

TRACKING_PARAMS = frozenset(
    {
        "gh_src",
        "lever-source",
        "lever-origin",
        "lever_source",
        "lever_origin",
        "source",
        "src",
        "ref",
        "referer",
        "referrer",
        "refid",
        "trackingid",
        "trk",
        "trkinfo",
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "yclid",
        "igshid",
        "si",
        "from",
        "vjs",
        "tk",
        "_ga",
        "_gl",
        "hsctatracking",
    }
)
TRACKING_PREFIXES = ("utm_", "pk_", "mc_", "hsa_", "_hs")

# ATS hosts whose "/apply" or "/application" page is the same job as the posting.
_APPLY_PAGE_HOSTS = ("lever.co", "greenhouse.io", "ashbyhq.com", "smartrecruiters.com")
_LINKEDIN_JOB_RE = re.compile(r"/(?:comm/)?jobs/view/(?:[^/]*?-)?(\d{6,})/?$")
_INDEED_JOB_PATHS = ("/viewjob", "/rc/clk", "/pagead/clk")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet")
_ALLOWED_PORTS = (None, 80, 443)


class UnsafeUrlError(AppError):
    status_code = 422
    code = "unsafe_url"


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def _normalized_host(hostname: str | None) -> str:
    host = (hostname or "").lower().rstrip(".")
    with contextlib.suppress(UnicodeError):  # keep the raw host when it is not valid IDNA
        host = host.encode("idna").decode("ascii")
    return host.removeprefix("www.")


def canonical_url(url: str) -> str:
    """Comparison key for a job URL (see the module docstring)."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme in ("http", "https", ""):
        scheme = "https"
    host = _normalized_host(parts.hostname)
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port in _ALLOWED_PORTS else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    query = parse_qsl(parts.query, keep_blank_values=True)

    if _host_matches(host, "linkedin.com"):
        match = _LINKEDIN_JOB_RE.search(path)
        if match:
            return f"https://linkedin.com/jobs/view/{match.group(1)}"
    if ".indeed." in f".{host}" and path.rstrip("/").endswith(_INDEED_JOB_PATHS):
        job_key = next((value for key, value in query if key == "jk" and value), None)
        if job_key:
            return f"https://{netloc}/viewjob?{urlencode({'jk': job_key})}"
    if any(_host_matches(host, domain) for domain in _APPLY_PAGE_HOSTS):
        path = re.sub(r"/(?:apply|application)/?$", "", path) or "/"

    if len(path) > 1:
        path = path.rstrip("/") or "/"
    kept = sorted((key, value) for key, value in query if not _is_tracking(key))
    return urlunsplit((scheme, netloc, path, urlencode(kept), ""))


def ats_type_from_url(url: str) -> AtsType:
    parts = urlsplit(url.strip())
    host = _normalized_host(parts.hostname)
    if _host_matches(host, "greenhouse.io") or "gh_jid=" in parts.query:
        return AtsType.GREENHOUSE
    for domain, ats_type in (
        ("lever.co", AtsType.LEVER),
        ("ashbyhq.com", AtsType.ASHBY),
        ("smartrecruiters.com", AtsType.SMARTRECRUITERS),
        ("myworkdayjobs.com", AtsType.WORKDAY),
        ("myworkdaysite.com", AtsType.WORKDAY),
        ("linkedin.com", AtsType.LINKEDIN),
    ):
        if _host_matches(host, domain):
            return ats_type
    if ".indeed." in f".{host}":
        return AtsType.INDEED
    return AtsType.GENERIC


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # Legacy IPv4 notations that resolvers accept: "127.1", "2130706433", "0x7f000001".
    if re.fullmatch(r"[0-9a-fx.]+", host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _is_private_host(host: str) -> bool:
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return True
    address = _parse_ip(host)
    if address is not None:
        return not address.is_global or address.is_multicast
    return "." not in host  # single-label names ("intranet") resolve inside the local network


def validate_public_url(url: str, *, max_length: int = MAX_URL_LENGTH) -> str:
    """Return ``url`` (trimmed) if it is a public http(s) URL, else raise ``UnsafeUrlError``."""
    value = url.strip() if isinstance(url, str) else ""
    if not value:
        raise UnsafeUrlError("A URL is required")
    if len(value) > max_length:
        raise UnsafeUrlError(f"The URL is longer than {max_length} characters")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs are accepted")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("URLs containing credentials are not accepted")
    if not parts.hostname:
        raise UnsafeUrlError("The URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("The URL has an invalid port") from exc
    if port not in _ALLOWED_PORTS:
        raise UnsafeUrlError("Only the standard web ports (80, 443) are accepted")
    if _is_private_host(parts.hostname):
        raise UnsafeUrlError("Private, local and internal addresses are not accepted")
    return value
