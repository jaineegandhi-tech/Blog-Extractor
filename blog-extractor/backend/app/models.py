"""
Database schema (§22).

CrawlJob        - one row per "Start Blog Extraction" click. Owns overall status/counters.
DiscoveredURL   - every URL found during discovery, with its classification and processing
                  status. This is the table that makes resume (§21) possible: on resume we
                  just re-queue rows whose status is not success/skipped/permanently_failed.
BlogResult      - one row per successfully (or partially) extracted blog = one Excel row (§7).
FailedURL       - denormalized failure log, exported as failed_urls.csv (§20). Kept separate
                  from DiscoveredURL.status so retry history isn't lost when a later retry
                  succeeds.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, Enum, ForeignKey, Boolean, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    DISCOVERING = "discovering"
    CRAWLING = "crawling"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"          # interrupted, resumable
    CANCELLED = "cancelled"


class URLStatus(str, enum.Enum):
    DISCOVERED = "discovered"      # found, not yet classified
    QUEUED = "queued"              # classified as blog, waiting to be crawled
    PROCESSING = "processing"
    SUCCESS = "success"
    PARTIAL = "partial"            # extracted but some fields missing/low confidence
    FAILED = "failed"              # failed this attempt, may retry
    PERMANENTLY_FAILED = "permanently_failed"  # exhausted retries
    SKIPPED = "skipped"            # classified as non-blog (login/cart/tag page/etc.)
    DUPLICATE = "duplicate"        # normalized/canonical duplicate of another row


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    website_url = Column(String, nullable=False)
    normalized_domain = Column(String, nullable=False, index=True)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)

    # config snapshot (so resume uses the same settings the job started with)
    config = Column(JSON, default=dict)

    # counters, updated as the job progresses (polled by the frontend)
    urls_discovered = Column(Integer, default=0)
    blogs_identified = Column(Integer, default=0)
    blogs_processed = Column(Integer, default=0)
    blogs_successful = Column(Integer, default=0)
    blogs_failed = Column(Integer, default=0)
    total_words_extracted = Column(Integer, default=0)
    current_url = Column(String, nullable=True)

    error_message = Column(Text, nullable=True)

    export_xlsx_path = Column(String, nullable=True)
    export_csv_path = Column(String, nullable=True)
    export_failed_csv_path = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    discovered_urls = relationship("DiscoveredURL", back_populates="job", cascade="all, delete-orphan")
    results = relationship("BlogResult", back_populates="job", cascade="all, delete-orphan")
    failures = relationship("FailedURL", back_populates="job", cascade="all, delete-orphan")


class DiscoveredURL(Base):
    __tablename__ = "discovered_urls"
    __table_args__ = (UniqueConstraint("job_id", "normalized_url", name="uq_job_normalized_url"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(String, ForeignKey("crawl_jobs.id"), nullable=False, index=True)

    raw_url = Column(String, nullable=False)
    normalized_url = Column(String, nullable=False, index=True)
    canonical_url = Column(String, nullable=True)

    source = Column(String, nullable=True)  # "sitemap", "nav_link", "pagination", "rss", etc.
    is_blog_candidate = Column(Boolean, default=False)
    classification_confidence = Column(Float, default=0.0)

    status = Column(Enum(URLStatus), default=URLStatus.DISCOVERED, nullable=False, index=True)
    http_status = Column(Integer, nullable=True)
    retry_count = Column(Integer, default=0)
    used_playwright = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("CrawlJob", back_populates="discovered_urls")


class BlogResult(Base):
    __tablename__ = "blog_results"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(String, ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    discovered_url_id = Column(String, ForeignKey("discovered_urls.id"), nullable=True)

    website = Column(String)
    blog_url = Column(String)
    canonical_url = Column(String)

    blog_title = Column(String)
    meta_title = Column(String)
    meta_description = Column(Text)

    author = Column(String)
    author_url = Column(String)
    publication_date = Column(String)
    last_updated_date = Column(String)

    category = Column(String)
    subcategory = Column(String)
    tags = Column(String)  # comma-separated
    featured_image_url = Column(String)

    word_count = Column(Integer, default=0)

    h1 = Column(Text)
    h2_headings = Column(Text)  # newline-separated, order preserved
    h3_headings = Column(Text)

    main_content = Column(Text)     # structured [H2]/[H3]-tagged full body, per §6
    introduction = Column(Text)
    conclusion = Column(Text)
    faq_content = Column(Text)

    extraction_status = Column(String)  # Success / Partial / Failed
    http_status = Column(Integer)
    extraction_date = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)

    job = relationship("CrawlJob", back_populates="results")


class FailedURL(Base):
    __tablename__ = "failed_urls"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(String, ForeignKey("crawl_jobs.id"), nullable=False, index=True)

    url = Column(String, nullable=False)
    error = Column(Text)
    http_status = Column(Integer, nullable=True)
    retry_count = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow)

    job = relationship("CrawlJob", back_populates="failures")
