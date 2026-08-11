"""
URL validation, normalization, and duplicate handling (§12 duplicate detection,
§26 security/SSRF protection).
"""
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from app.config import settings

# Query params that are safe to strip because they don't change page content
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source", "amp",
}


class UnsafeURLError(ValueError):
    pass


def normalize_url(raw_url: str) -> str:
    """
    Normalize a URL for deduplication (§12):
    - lowercase scheme/host
    - force https unless explicitly http-only source
    - strip default ports, fragments, trailing slash (except root)
    - strip known tracking query params, sort remaining ones
    """
    parts = urlsplit(raw_url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    netloc = netloc.split(":")[0]  # drop default ports for normalization purposes

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    kept_qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
               if k.lower() not in TRACKING_PARAMS]
    kept_qs.sort()
    query = urlencode(kept_qs)

    return urlunsplit((scheme, netloc, path, query, ""))  # fragment dropped


def get_domain(url: str) -> str:
    netloc = urlsplit(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(":")[0]


def is_same_site(url: str, root_domain: str) -> bool:
    domain = get_domain(url)
    return domain == root_domain or domain.endswith("." + root_domain)


def validate_public_url(url: str) -> None:
    """
    SSRF guard (§26): reject localhost, loopback, link-local, private, and
    reserved IP ranges, whether given directly or via DNS resolution.
    Raises UnsafeURLError if the URL must not be fetched.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Unsupported scheme: {parts.scheme}")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname")

    if hostname.lower() in settings.BLOCKED_HOSTS:
        raise UnsafeURLError(f"Blocked host: {hostname}")

    # Direct-IP case
    try:
        ip = ipaddress.ip_address(hostname)
        _reject_if_unsafe_ip(ip)
        return
    except ValueError:
        pass  # not a literal IP, fall through to DNS resolution

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"DNS resolution failed for {hostname}: {e}")

    for family, _, _, _, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        _reject_if_unsafe_ip(ip)


def _reject_if_unsafe_ip(ip: ipaddress._BaseAddress) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise UnsafeURLError(f"Blocked internal/private IP: {ip}")


NON_BLOG_PATH_SEGMENTS = {
    "login", "signin", "sign-in", "signup", "sign-up", "register",
    "contact", "contact-us", "privacy", "privacy-policy", "terms",
    "terms-of-service", "terms-and-conditions", "careers", "jobs",
    "cart", "checkout", "account", "my-account", "wp-admin", "wp-login",
    "search", "tag", "tags", "author", "page", "category-listing",
}


def looks_like_non_blog_path(url: str) -> bool:
    path = urlsplit(url).path.lower().strip("/")
    if not path:
        return True  # homepage itself isn't an article
    segments = set(path.split("/"))
    return bool(segments & NON_BLOG_PATH_SEGMENTS)
