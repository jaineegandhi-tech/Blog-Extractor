"""
Article extraction engine (§5, §6, §8, §14, §15).

Strategy:
1. Run trafilatura for main-content isolation (handles boilerplate removal --
   nav/footer/ads/cookie banners/related-posts/social-share -- far better than
   naive <body> extraction, per §14).
2. Parse JSON-LD / OpenGraph / Twitter-card metadata directly with BeautifulSoup
   for structured fields trafilatura doesn't fully expose (author URL, tags,
   featured image, dateModified).
3. Re-walk the *original* article DOM subtree (found via <article>/<main>/content-
   density heuristics) to rebuild an [H1]/[H2]/[H3]-tagged structured version of
   the body (§6), and split it into Introduction / Main Content / Conclusion / FAQ
   (§8).
"""
import json
import re
from dataclasses import dataclass, field

import trafilatura
from bs4 import BeautifulSoup, Tag

NOISE_TAGS = ["script", "style", "noscript", "iframe", "svg", "form"]
NOISE_SELECTORS = [
    "nav", "footer", "header", "aside",
    "[class*=cookie]", "[id*=cookie]",
    "[class*=newsletter]", "[class*=subscribe]",
    "[class*=advert]", "[class*=advertisement]", "[id*=advert]",
    "[class*=sidebar]", "[id*=sidebar]",
    "[class*=related-post]", "[class*=related_posts]", "[class*=you-may-like]",
    "[class*=share]", "[class*=social-share]",
    "[class*=comment]", "[id*=comment]",
    "[class*=popup]", "[class*=modal]",
    "[class*=breadcrumb]",
]

FAQ_HEADING_RE = re.compile(r"\bfaq\b|frequently asked questions", re.I)
CONCLUSION_HEADING_RE = re.compile(r"\bconclusion\b|final thoughts|wrapping up|in summary|to summarize", re.I)


@dataclass
class ExtractedArticle:
    title: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    author: str | None = None
    author_url: str | None = None
    published_date: str | None = None
    modified_date: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    featured_image: str | None = None

    h1: str | None = None
    h2_headings: list[str] = field(default_factory=list)
    h3_headings: list[str] = field(default_factory=list)

    structured_content: str = ""   # [H1]/[H2]/[H3]-tagged full body, §6
    introduction: str = ""
    main_content: str = ""
    conclusion: str = ""
    faq_content: str = ""

    word_count: int = 0
    quality_ok: bool = True
    warnings: list[str] = field(default_factory=list)


def _clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    for tag_name in NOISE_TAGS:
        for t in soup.find_all(tag_name):
            t.decompose()
    for selector in NOISE_SELECTORS:
        for t in soup.select(selector):
            t.decompose()
    return soup


def _find_main_container(soup: BeautifulSoup) -> Tag | None:
    """§14: prefer <article>, then <main>, then the densest content block."""
    article = soup.find("article")
    if article and len(article.get_text(strip=True)) > 200:
        return article
    main = soup.find("main")
    if main and len(main.get_text(strip=True)) > 200:
        return main

    # Fallback: pick the element with the highest text-to-tag density among
    # common content wrapper patterns.
    candidates = soup.select(
        "[class*=post-content], [class*=entry-content], [class*=article-content], "
        "[class*=article-body], [id*=content], [class*=content]"
    )
    best, best_len = None, 0
    for c in candidates:
        text_len = len(c.get_text(strip=True))
        if text_len > best_len:
            best, best_len = c, text_len
    if best is not None and best_len > 200:
        return best
    return soup.body or soup


def _extract_json_ld(soup: BeautifulSoup) -> dict:
    merged: dict = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            candidates = data["@graph"]
        for c in candidates:
            if not isinstance(c, dict):
                continue
            t = c.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(x in {"Article", "BlogPosting", "NewsArticle", "TechArticle"} for x in types if x):
                merged.update(c)
    return merged


def _meta(soup: BeautifulSoup, **attrs) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    return tag.get("content").strip() if tag and tag.get("content") else None


def _extract_metadata(soup: BeautifulSoup, url: str) -> ExtractedArticle:
    a = ExtractedArticle()
    jsonld = _extract_json_ld(soup)

    title_tag = soup.find("title")
    a.meta_title = title_tag.get_text(strip=True) if title_tag else None
    a.meta_description = _meta(soup, name="description") or _meta(soup, property="og:description")

    canonical = soup.find("link", rel="canonical")
    a.canonical_url = canonical.get("href").strip() if canonical and canonical.get("href") else url

    # Author
    author = jsonld.get("author")
    if isinstance(author, dict):
        a.author = author.get("name")
        a.author_url = author.get("url")
    elif isinstance(author, list) and author:
        first = author[0]
        if isinstance(first, dict):
            a.author = first.get("name")
            a.author_url = first.get("url")
    elif isinstance(author, str):
        a.author = author
    if not a.author:
        a.author = _meta(soup, name="author")
        byline = soup.find(attrs={"class": re.compile("author", re.I)})
        if not a.author and byline:
            a.author = byline.get_text(strip=True)

    a.published_date = jsonld.get("datePublished") or _meta(soup, property="article:published_time")
    a.modified_date = jsonld.get("dateModified") or _meta(soup, property="article:modified_time")

    section = jsonld.get("articleSection")
    if isinstance(section, list):
        a.category = section[0] if section else None
    elif isinstance(section, str):
        a.category = section
    if not a.category:
        a.category = _meta(soup, property="article:section")

    tags = jsonld.get("keywords")
    if isinstance(tags, str):
        a.tags = [t.strip() for t in re.split(r",|;", tags) if t.strip()]
    elif isinstance(tags, list):
        a.tags = [str(t).strip() for t in tags]
    if not a.tags:
        a.tags = [m.get("content").strip() for m in soup.find_all("meta", property="article:tag")
                  if m.get("content")]

    image = jsonld.get("image")
    if isinstance(image, dict):
        a.featured_image = image.get("url")
    elif isinstance(image, list) and image:
        a.featured_image = image[0] if isinstance(image[0], str) else image[0].get("url")
    elif isinstance(image, str):
        a.featured_image = image
    if not a.featured_image:
        a.featured_image = _meta(soup, property="og:image")

    a.h1 = soup.find("h1").get_text(strip=True) if soup.find("h1") else None
    a.title = jsonld.get("headline") or a.h1 or a.meta_title

    return a


def _build_structured_content(container: Tag) -> tuple[str, list[str], list[str], str, str, str, str]:
    """
    Walks the main content container top-to-bottom, emitting a structured
    [H1]/[H2]/[H3]-tagged transcript (§6), and splits it into introduction /
    main body / conclusion / FAQ (§8). Preserves lists, tables, and blockquotes.
    """
    lines: list[str] = []
    h2_list, h3_list = [], []
    faq_lines: list[str] = []
    in_faq = False

    blocks = container.find_all(
        ["h1", "h2", "h3", "h4", "p", "ul", "ol", "blockquote", "table"], recursive=True
    )

    for el in blocks:
        # Skip elements nested inside another already-captured block (avoid dup text
        # from e.g. a <p> inside a <blockquote> being walked twice).
        if el.find_parent(["blockquote", "table", "ul", "ol"]) and el.name not in (
            "blockquote", "table", "ul", "ol"
        ):
            continue

        if el.name in ("h1", "h2", "h3", "h4"):
            text = el.get_text(strip=True)
            if not text:
                continue
            tag = {"h1": "[H1]", "h2": "[H2]", "h3": "[H3]", "h4": "[H3]"}[el.name]
            lines.append(f"\n{tag} {text}\n")
            if el.name == "h2":
                h2_list.append(text)
            elif el.name in ("h3", "h4"):
                h3_list.append(text)
            in_faq = bool(FAQ_HEADING_RE.search(text))

        elif el.name == "p":
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(text)
                if in_faq:
                    faq_lines.append(text)

        elif el.name in ("ul", "ol"):
            items = [li.get_text(" ", strip=True) for li in el.find_all("li", recursive=False)]
            items = [i for i in items if i]
            if items:
                bullet = "-" if el.name == "ul" else "1."
                block = "\n".join(f"{bullet} {i}" for i in items)
                lines.append(block)
                if in_faq:
                    faq_lines.append(block)

        elif el.name == "blockquote":
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(f'> "{text}"')

        elif el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                lines.append("\n".join(rows))

    structured = "\n".join(lines).strip()

    # Split introduction: text before the first H2 (or first ~2 paragraphs).
    first_h2_idx = structured.find("[H2]")
    if first_h2_idx > 0:
        introduction = structured[:first_h2_idx].strip()
        main_content = structured[first_h2_idx:].strip()
    else:
        paras = structured.split("\n\n")
        introduction = paras[0].strip() if paras else ""
        main_content = structured

    # Conclusion: last [H2]/[H3] section whose heading matches conclusion patterns,
    # else the final paragraph block of main_content.
    conclusion = ""
    sections = re.split(r"(?=\[H2\]|\[H3\])", main_content)
    for sec in reversed(sections):
        heading_line = sec.strip().split("\n", 1)[0]
        if CONCLUSION_HEADING_RE.search(heading_line):
            conclusion = sec.strip()
            break

    faq_content = "\n".join(faq_lines).strip()

    return structured, h2_list, h3_list, introduction, main_content, conclusion, faq_content


def extract_article(html: str, url: str) -> ExtractedArticle:
    raw_soup = BeautifulSoup(html, "lxml")
    meta = _extract_metadata(raw_soup, url)

    clean_soup = _clean_soup(BeautifulSoup(html, "lxml"))
    container = _find_main_container(clean_soup)

    structured, h2s, h3s, intro, body, conclusion, faq = _build_structured_content(container)

    # Cross-check with trafilatura's extraction for word-count sanity / fallback
    # when our DOM-based approach comes up too short (e.g. unusual markup).
    traf_text = trafilatura.extract(html, include_tables=True, include_formatting=False) or ""
    if len(body.split()) < 50 and len(traf_text.split()) > len(body.split()):
        body = traf_text
        structured = structured or traf_text
        meta.warnings.append("Fell back to trafilatura extraction (DOM-based body was too short)")

    meta.h2_headings = h2s
    meta.h3_headings = h3s
    meta.structured_content = structured
    meta.introduction = intro
    meta.main_content = body
    meta.conclusion = conclusion
    meta.faq_content = faq
    meta.word_count = len(structured.split())

    if meta.word_count < 50:
        meta.quality_ok = False
        meta.warnings.append("Extracted word count below quality threshold (possible extraction failure)")

    return meta
