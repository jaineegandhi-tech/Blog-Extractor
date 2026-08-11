"""
Sitemap discovery and parsing (§3), prioritized as the primary URL source since
it's the cheapest and most reliable way to get complete coverage of large sites.
"""
import gzip
import io
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from app.config import settings

COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/post-sitemap.xml",
    "/blog-sitemap.xml",
    "/page-sitemap.xml",
    "/sitemap/sitemap.xml",
    "/wp-sitemap.xml",  # modern WordPress core sitemap
]

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resp = await client.get(url, headers={"User-Agent": settings.USER_AGENT},
                                 timeout=settings.REQUEST_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        content = resp.content
        if url.endswith(".gz") or resp.headers.get("content-type", "").endswith("gzip"):
            try:
                content = gzip.decompress(content)
            except OSError:
                pass
        return content
    except Exception:
        return None


def _parse_sitemap_xml(content: bytes):
    """Returns (child_sitemap_urls, page_urls_with_lastmod)."""
    child_sitemaps, pages = [], []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return child_sitemaps, pages

    tag = root.tag.lower()
    if tag.endswith("sitemapindex"):
        for sm in root.findall("sm:sitemap", NS):
            loc = sm.find("sm:loc", NS)
            if loc is not None and loc.text:
                child_sitemaps.append(loc.text.strip())
    elif tag.endswith("urlset"):
        for u in root.findall("sm:url", NS):
            loc = u.find("sm:loc", NS)
            if loc is None or not loc.text:
                continue
            lastmod_el = u.find("sm:lastmod", NS)
            pages.append({
                "url": loc.text.strip(),
                "lastmod": lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None,
            })
    return child_sitemaps, pages


async def discover_sitemap_urls(base_url: str, max_urls: int = 20000) -> list[dict]:
    """
    Finds and recursively parses all sitemaps for a domain, following robots.txt
    Sitemap: directives too. Returns a deduped list of {url, lastmod, source}.
    """
    results: dict[str, dict] = {}
    seen_sitemaps: set[str] = set()
    to_process: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # 1. robots.txt Sitemap: directives
        robots_content = await _fetch(client, urljoin(base_url, "/robots.txt"))
        if robots_content:
            for line in robots_content.decode("utf-8", errors="ignore").splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    to_process.append(line.split(":", 1)[1].strip())

        # 2. common well-known locations
        for path in COMMON_SITEMAP_PATHS:
            to_process.append(urljoin(base_url, path))

        while to_process and len(results) < max_urls:
            sm_url = to_process.pop(0)
            if sm_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sm_url)

            content = await _fetch(client, sm_url)
            if not content:
                continue

            children, pages = _parse_sitemap_xml(content)
            for child in children:
                if child not in seen_sitemaps:
                    to_process.append(child)
            for p in pages:
                if len(results) >= max_urls:
                    break
                results.setdefault(p["url"], {"url": p["url"], "lastmod": p["lastmod"], "source": "sitemap"})

    return list(results.values())
