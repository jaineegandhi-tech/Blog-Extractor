"""
Page fetching (§13 JS websites). Tries a plain async HTTP GET first (cheap, fast);
if the resulting HTML looks too thin to be a real article (few words, no paragraph
text), falls back to a headless Playwright browser render. This two-tier approach
avoids paying for a full browser on every one of possibly thousands of pages while
still supporting React/Next.js/Vue/Angular sites whose content is client-rendered.
"""
import asyncio
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_pw_instance = None
_pw_browser = None

async def init_browser():
    global _pw_instance, _pw_browser
    from playwright.async_api import async_playwright
    if _pw_instance is None:
        _pw_instance = await async_playwright().start()
        _pw_browser = await _pw_instance.chromium.launch(headless=True)

async def close_browser():
    global _pw_instance, _pw_browser
    if _pw_browser:
        await _pw_browser.close()
        _pw_browser = None
    if _pw_instance:
        await _pw_instance.stop()
        _pw_instance = None


@dataclass
class FetchResult:
    url: str
    final_url: str
    http_status: int
    html: str | None
    used_playwright: bool
    error: str | None = None


def _quick_word_count(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return len(text.split())


async def fetch_static(client: httpx.AsyncClient, url: str) -> FetchResult:
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        return FetchResult(
            url=url, final_url=str(resp.url), http_status=resp.status_code,
            html=resp.text if resp.status_code == 200 else None,
            used_playwright=False,
            error=None if resp.status_code == 200 else f"HTTP {resp.status_code}",
        )
    except httpx.TimeoutException:
        return FetchResult(url=url, final_url=url, http_status=0, html=None,
                            used_playwright=False, error="Timeout")
    except Exception as e:
        return FetchResult(url=url, final_url=url, http_status=0, html=None,
                            used_playwright=False, error=str(e))


async def fetch_with_playwright(url: str) -> FetchResult:
    """
    Renders the page in headless Chromium and returns the post-JS DOM.
    Reuses a global browser instance initialized at the start of the crawl job.
    """
    from playwright.async_api import TimeoutError as PWTimeout
    global _pw_browser

    if _pw_browser is None:
        await init_browser()

    try:
        page = await _pw_browser.new_page(user_agent=settings.USER_AGENT)
        try:
            response = await page.goto(
                url, timeout=settings.PLAYWRIGHT_NAV_TIMEOUT_MS, wait_until="networkidle"
            )
            # Give lazy-loaded / infinite-scroll content a chance to mount.
            try:
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(800)
            except Exception:
                pass
            html = await page.content()
            status = response.status if response else 0
            return FetchResult(url=url, final_url=page.url, http_status=status,
                                html=html, used_playwright=True)
        finally:
            await page.close()
    except PWTimeout:
        return FetchResult(url=url, final_url=url, http_status=0, html=None,
                            used_playwright=True, error="Playwright navigation timeout")
    except Exception as e:
        return FetchResult(url=url, final_url=url, http_status=0, html=None,
                            used_playwright=True, error=f"Playwright error: {e}")


async def fetch_page(client: httpx.AsyncClient, url: str) -> FetchResult:
    """Static-first with automatic Playwright fallback when content looks JS-gated."""
    result = await fetch_static(client, url)
    if result.html:
        word_count = await asyncio.to_thread(_quick_word_count, result.html)
        if word_count >= settings.JS_RENDER_WORD_COUNT_THRESHOLD:
            return result

    # Thin/empty content (or failed request) -> try a real browser render.
    pw_result = await fetch_with_playwright(url)
    if pw_result.html:
        return pw_result
    # If Playwright also failed, prefer returning the original static result
    # (it may still have a usable HTTP status/error even without full content).
    return result if result.html else pw_result


async def fetch_with_retries(client: httpx.AsyncClient, url: str, max_retries: int) -> FetchResult:
    last: FetchResult | None = None
    for attempt in range(max_retries + 1):
        last = await fetch_page(client, url)
        if last.html and last.http_status == 200:
            return last
        if attempt < max_retries:
            await asyncio.sleep(min(2 ** attempt, 10))  # exponential backoff
    return last
