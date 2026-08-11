from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, HttpUrl, field_validator


class CrawlCreateRequest(BaseModel):
    url: str
    max_concurrent_requests: Optional[int] = None
    request_delay_seconds: Optional[float] = None
    max_urls: Optional[int] = None

    @field_validator("url")
    @classmethod
    def must_have_scheme(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("http://") and not v.startswith("https://"):
            v = "https://" + v
        return v


class CrawlCreateResponse(BaseModel):
    job_id: str
    status: str


class CrawlStatusResponse(BaseModel):
    job_id: str
    website_url: str
    status: str
    urls_discovered: int
    blogs_identified: int
    blogs_processed: int
    blogs_successful: int
    blogs_failed: int
    remaining: int
    progress_percent: float
    total_words_extracted: int
    current_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    exports_ready: bool

    class Config:
        from_attributes = True


class BlogResultOut(BaseModel):
    id: str
    blog_url: str
    blog_title: Optional[str] = None
    author: Optional[str] = None
    publication_date: Optional[str] = None
    word_count: int
    extraction_status: str

    class Config:
        from_attributes = True


class CrawlResultsResponse(BaseModel):
    job_id: str
    total: int
    results: List[BlogResultOut]


class FailedURLOut(BaseModel):
    url: str
    error: Optional[str]
    http_status: Optional[int]
    retry_count: int
    timestamp: datetime

    class Config:
        from_attributes = True
