"""
Job orchestration (§9, §21, §24).

Design decision: rather than fan out one Celery task per URL (which makes
concurrency/rate-limiting across thousands of tasks hard to reason about and
adds broker overhead), a single Celery task runs the *entire* job and manages
concurrency internally with an asyncio.Semaphore + shared httpx.AsyncClient.
This keeps "max concurrent requests" and "request delay" exactly enforceable
per §16, and keeps Celery's job purely as "one job = one worker slot", which
is what actually needs to scale (many jobs across many websites at once).

Progress is committed to Postgres after every processed URL (not batched),
so the dashboard's polling (§10) and resume-after-crash (§21) both just read
current DB state -- there is no separate in-memory progress store to lose.
"""
import asyncio
import logging

import httpx
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import settings
from app.models import CrawlJob, DiscoveredURL, BlogResult, FailedURL, JobStatus, URLStatus
from app.services import sitemap as sitemap_svc
from app.services import discovery as discovery_svc
from app.services import classifier as classifier_svc
from app.services import extractor as extractor_svc
from app.services.fetcher import fetch_with_retries, init_browser, close_browser
from app.services.robots import RobotsCache
from app.services.url_utils import normalize_url, get_domain, validate_public_url, UnsafeURLError
from app.services.exporter import export_xlsx, export_csv, export_failed_urls_csv
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _update_job(db: Session, job: CrawlJob, **fields):
    for k, v in fields.items():
        setattr(job, k, v)
    db.add(job)
    db.commit()


async def _run_discovery(db: Session, job: CrawlJob):
    """§2, §3, §4: sitemap-first, then supplementary crawl + RSS."""
    _update_job(db, job, status=JobStatus.DISCOVERING)
    root_domain = job.normalized_domain
    base = f"https://{root_domain}"

    collected: dict[str, dict] = {}

    sitemap_urls = await sitemap_svc.discover_sitemap_urls(base, max_urls=settings.MAX_URLS_TO_DISCOVER)
    for u in sitemap_urls:
        collected.setdefault(u["url"], u)

    if len(collected) < 5:  # sitemap missing/sparse -> fall back to link crawling
        crawled = await discovery_svc.crawl_for_blog_links(
            base, root_domain,
            max_urls=settings.MAX_URLS_TO_DISCOVER,
            max_pagination_depth=settings.MAX_PAGINATION_DEPTH,
        )
        for u in crawled:
            collected.setdefault(u["url"], u)

        rss_urls = await discovery_svc.discover_rss_urls(base)
        for u in rss_urls:
            collected.setdefault(u, {"url": u, "lastmod": None, "source": "rss"})

    # Persist, deduped by normalized URL (§12)
    seen_normalized: set[str] = set()
    inserted = 0
    for entry in collected.values():
        try:
            validate_public_url(entry["url"])
        except UnsafeURLError:
            continue
        norm = normalize_url(entry["url"])
        if norm in seen_normalized:
            continue
        seen_normalized.add(norm)

        exists = db.query(DiscoveredURL).filter_by(job_id=job.id, normalized_url=norm).first()
        if exists:
            continue

        is_candidate = classifier_svc.url_looks_like_blog(entry["url"])
        db.add(DiscoveredURL(
            job_id=job.id,
            raw_url=entry["url"],
            normalized_url=norm,
            source=entry.get("source", "sitemap"),
            is_blog_candidate=is_candidate,
            status=URLStatus.QUEUED if is_candidate else URLStatus.SKIPPED,
        ))
        inserted += 1
        if inserted % 200 == 0:
            db.commit()

    db.commit()

    urls_discovered = db.query(DiscoveredURL).filter_by(job_id=job.id).count()
    blogs_identified = db.query(DiscoveredURL).filter_by(
        job_id=job.id, is_blog_candidate=True
    ).count()
    _update_job(db, job, urls_discovered=urls_discovered, blogs_identified=blogs_identified)


async def _process_one(
    client: httpx.AsyncClient,
    robots: RobotsCache,
    job: CrawlJob,
    url_row: DiscoveredURL,
    db_factory,
):
    """Fetch + extract + classify-by-content + persist a single URL's result."""
    if settings.RESPECT_ROBOTS_TXT and not await robots.can_fetch(url_row.raw_url):
        db = db_factory()
        try:
            url_row = db.merge(url_row)
            url_row.status = URLStatus.SKIPPED
            db.commit()
        finally:
            db.close()
        return

    fetch_result = await fetch_with_retries(client, url_row.raw_url, settings.MAX_RETRIES)

    db = db_factory()
    try:
        url_row = db.merge(url_row)
        job_local = db.merge(job)

        if not fetch_result.html:
            url_row.status = URLStatus.FAILED if url_row.retry_count < settings.MAX_RETRIES else URLStatus.PERMANENTLY_FAILED
            url_row.http_status = fetch_result.http_status
            url_row.retry_count += 1
            db.add(FailedURL(
                job_id=job.id, url=url_row.raw_url, error=fetch_result.error or "Unknown fetch error",
                http_status=fetch_result.http_status, retry_count=url_row.retry_count,
            ))
            job_local.blogs_processed += 1
            job_local.blogs_failed += 1
            db.commit()
            return

        # Content-based classification refinement (§3): a URL that *looked*
        # like a blog by path may still not be one; conversely, keep as-is if
        # URL heuristics already said no (we wouldn't be here in that case).
        is_blog, confidence = await asyncio.to_thread(
            classifier_svc.classify_page_content, fetch_result.html, url_row.raw_url
        )
        url_row.classification_confidence = confidence
        if not is_blog:
            url_row.status = URLStatus.SKIPPED
            job_local.blogs_processed += 1
            db.commit()
            return

        article = await asyncio.to_thread(
            extractor_svc.extract_article, fetch_result.html, fetch_result.final_url
        )
        url_row.used_playwright = fetch_result.used_playwright
        url_row.http_status = fetch_result.http_status

        status = "Success" if article.quality_ok else "Partial"
        url_row.status = URLStatus.SUCCESS if article.quality_ok else URLStatus.PARTIAL

        db.add(BlogResult(
            job_id=job.id,
            discovered_url_id=url_row.id,
            website=f"https://{job.normalized_domain}",
            blog_url=fetch_result.final_url,
            canonical_url=article.canonical_url,
            blog_title=article.title,
            meta_title=article.meta_title,
            meta_description=article.meta_description,
            author=article.author,
            author_url=article.author_url,
            publication_date=article.published_date,
            last_updated_date=article.modified_date,
            category=article.category,
            subcategory=None,
            tags=", ".join(article.tags) if article.tags else None,
            featured_image_url=article.featured_image,
            word_count=article.word_count,
            h1=article.h1,
            h2_headings="\n".join(article.h2_headings),
            h3_headings="\n".join(article.h3_headings),
            main_content=article.structured_content,
            introduction=article.introduction,
            conclusion=article.conclusion,
            faq_content=article.faq_content,
            extraction_status=status,
            http_status=fetch_result.http_status,
            error_message="; ".join(article.warnings) if article.warnings else None,
        ))

        job_local.blogs_processed += 1
        job_local.blogs_successful += 1
        job_local.total_words_extracted += article.word_count
        job_local.current_url = url_row.raw_url
        db.commit()
    finally:
        db.close()


async def _run_crawl(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(CrawlJob).get(job_id)
        if job is None:
            return

        if job.urls_discovered == 0:
            await _run_discovery(db, job)
            db.refresh(job)

        if job.status == JobStatus.CANCELLED:
            logger.info(f"Crawl job {job.id} was cancelled during discovery.")
            return

        _update_job(db, job, status=JobStatus.CRAWLING)

        pending = (
            db.query(DiscoveredURL)
            .filter(DiscoveredURL.job_id == job.id)
            .filter(DiscoveredURL.status.in_([URLStatus.QUEUED, URLStatus.FAILED]))
            .all()
        )

        semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        robots = RobotsCache()

        # Initialize the global Playwright browser for this job
        await init_browser()

        async def _bounded(client, url_row):
            async with semaphore:
                await asyncio.sleep(settings.REQUEST_DELAY_SECONDS)  # global ethical rate limit
                await _process_one(client, robots, job, url_row, SessionLocal)

        try:
            async with httpx.AsyncClient(
                limits=httpx.Limits(max_connections=settings.MAX_CONCURRENT_REQUESTS)
            ) as client:
                # Process in chunks so a crash mid-job only loses the in-flight chunk,
                # not the whole run (state for completed URLs is already committed).
                chunk_size = settings.MAX_CONCURRENT_REQUESTS * 4
                for i in range(0, len(pending), chunk_size):
                    db.refresh(job)
                    if job.status == JobStatus.CANCELLED:
                        logger.info(f"Crawl job {job.id} was cancelled by the user. Stopping extraction.")
                        return

                    chunk = pending[i:i + chunk_size]
                    await asyncio.gather(*[_bounded(client, u) for u in chunk], return_exceptions=True)
        finally:
            await close_browser()

        db.refresh(job)
        remaining = db.query(DiscoveredURL).filter(
            DiscoveredURL.job_id == job.id,
            DiscoveredURL.status.in_([URLStatus.QUEUED, URLStatus.FAILED]),
        ).count()

        if remaining > 0:
            _update_job(db, job, status=JobStatus.PAUSED)
            return

        xlsx_path = export_xlsx(db, job)
        csv_path = export_csv(db, job)
        failed_csv_path = export_failed_urls_csv(db, job)

        from datetime import datetime
        _update_job(
            db, job,
            status=JobStatus.COMPLETED,
            export_xlsx_path=xlsx_path,
            export_csv_path=csv_path,
            export_failed_csv_path=failed_csv_path,
            completed_at=datetime.utcnow(),
            current_url=None,
        )
    except Exception as e:
        logger.exception("Crawl job %s failed", job_id)
        job = db.query(CrawlJob).get(job_id)
        if job:
            _update_job(db, job, status=JobStatus.FAILED, error_message=str(e))
    finally:
        db.close()


@celery_app.task(name="run_crawl_job")
def run_crawl_job(job_id: str):
    asyncio.run(_run_crawl(job_id))


@celery_app.task(name="resume_crawl_job")
def resume_crawl_job(job_id: str):
    """§21: resume simply re-invokes the same pipeline; discovery is skipped
    if urls_discovered > 0, and only QUEUED/FAILED rows get re-processed."""
    asyncio.run(_run_crawl(job_id))
