"""
Ethical crawling: respect robots.txt (§16).
Cached per-domain within a job run to avoid refetching for every URL.
"""
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

from app.config import settings


class RobotsCache:
    def __init__(self):
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def _load(self, domain_root: str) -> urllib.robotparser.RobotFileParser:
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{domain_root}/robots.txt"
        try:
            async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.get(robots_url, headers={"User-Agent": settings.USER_AGENT})
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])  # no robots.txt / inaccessible -> treat as allow-all
        except Exception:
            rp.parse([])
        return rp

    async def can_fetch(self, url: str) -> bool:
        if not settings.RESPECT_ROBOTS_TXT:
            return True
        parts = urlsplit(url)
        domain_root = f"{parts.scheme}://{parts.netloc}"
        if domain_root not in self._cache:
            self._cache[domain_root] = await self._load(domain_root)
        return self._cache[domain_root].can_fetch(settings.USER_AGENT, url)

    async def crawl_delay(self, url: str) -> float | None:
        parts = urlsplit(url)
        domain_root = f"{parts.scheme}://{parts.netloc}"
        rp = self._cache.get(domain_root)
        if rp is None:
            return None
        delay = rp.crawl_delay(settings.USER_AGENT)
        return float(delay) if delay else None
