"""
Fallback / supplementary discovery when sitemaps are missing or incomplete (§2, §4).
Crawls the homepage, common blog-index paths, and follows pagination + internal
links breadth-first up to configured limits, plus RSS feed parsing.
"""
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.url_utils import is_same_site, get_domain

COMMON_BLOG_INDEX_PATHS = [
    "/blog", "/blog/", "/articles", "/articles/", "/resources", "/resources/",
    "/news", "/news/", "/insights", "/insights/", "/guides", "/guides/",
    "/case-studies", "/case-studies/", "/press", "/updates",
]

COMMON_RSS_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/blog/feed"]

BLOG_URL_HINT_RE = re.compile(
    r"/(blog|article|articles|post|posts|news|insights?|resources?|guides?|"
    r"case-studies?|stories|updates?)/", re.I,
)


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        resp = await client.get(url, headers={"User-Agent": settings.USER_AGENT},
                                 timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
        return resp
    except Exception:
        return None


async def discover_rss_urls(base_url: str) -> list[str]:
    urls = []
    async with httpx.AsyncClient() as client:
        for path in COMMON_RSS_PATHS:
            resp = await _get(client, urljoin(base_url, path))
            if not resp or resp.status_code != 200:
                continue
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                continue
            # RSS 2.0: <item><link>...
            for link_el in root.iter():
                if link_el.tag.lower().endswith("link") and link_el.text:
                    urls.append(link_el.text.strip())
    return urls


async def crawl_for_blog_links(
    base_url: str,
    root_domain: str,
    max_urls: int = 20000,
    max_pagination_depth: int = 500,
) -> list[dict]:
    """
    Breadth-first crawl starting from the homepage + common blog-index paths.
    Follows: nav/footer internal links, pagination links, and links that live
    inside elements resembling article/post lists. Does not fetch full article
    pages here -- that's the extraction stage's job. This stage only harvests URLs.
    """
    seen: set[str] = set()
    results: dict[str, dict] = {}
    queue: list[tuple[str, int]] = [(base_url, 0)]
    for path in COMMON_BLOG_INDEX_PATHS:
        queue.append((urljoin(base_url, path), 0))

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=settings.MAX_CONCURRENT_REQUESTS)) as client:
        while queue and len(results) < max_urls:
            url, depth = queue.pop(0)
            norm = url.split("#")[0]
            if norm in seen or depth > max_pagination_depth:
                continue
            seen.add(norm)

            resp = await _get(client, url)
            if not resp or resp.status_code != 200:
                continue
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            pagination_links = []

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                    continue
                full = urljoin(url, href)
                if not is_same_site(full, root_domain):
                    continue
                full = full.split("#")[0]

                is_pagination = bool(re.search(r"/page/\d+|[?&]page=\d+|[?&]paged=\d+", full))
                looks_like_blog = bool(BLOG_URL_HINT_RE.search(urlsplit(full).path))

                if is_pagination and full not in seen:
                    pagination_links.append(full)
                elif looks_like_blog:
                    results.setdefault(full, {"url": full, "lastmod": None, "source": "internal_link"})

            # follow pagination further (bounded by max_pagination_depth)
            for p_url in pagination_links:
                if p_url not in seen:
                    queue.append((p_url, depth + 1))

    return list(results.values())
