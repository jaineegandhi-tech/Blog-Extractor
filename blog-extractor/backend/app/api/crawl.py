import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CrawlJob, BlogResult, FailedURL, JobStatus
from app.schemas import (
    CrawlCreateRequest, CrawlCreateResponse, CrawlStatusResponse,
    CrawlResultsResponse, BlogResultOut, FailedURLOut,
)
from app.services.url_utils import get_domain, validate_public_url, UnsafeURLError
from app.workers.tasks import run_crawl_job, resume_crawl_job

router = APIRouter(prefix="/crawl", tags=["crawl"])


@router.post("", response_model=CrawlCreateResponse)
def create_crawl(payload: CrawlCreateRequest, db: Session = Depends(get_db)):
    """POST /api/crawl -- creates a new crawl job and enqueues the background pipeline."""
    try:
        validate_public_url(payload.url)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))

    domain = get_domain(payload.url)
    config = {}
    if payload.max_concurrent_requests:
        config["max_concurrent_requests"] = payload.max_concurrent_requests
    if payload.request_delay_seconds is not None:
        config["request_delay_seconds"] = payload.request_delay_seconds
    if payload.max_urls:
        config["max_urls"] = payload.max_urls

    job = CrawlJob(website_url=payload.url, normalized_domain=domain,
                    status=JobStatus.PENDING, config=config)
    db.add(job)
    db.commit()
    db.refresh(job)

    run_crawl_job.delay(job.id)

    return CrawlCreateResponse(job_id=job.id, status=job.status.value)


def _to_status_response(job: CrawlJob) -> CrawlStatusResponse:
    remaining = max(job.blogs_identified - job.blogs_processed, 0)
    progress = (job.blogs_processed / job.blogs_identified * 100) if job.blogs_identified else 0.0
    return CrawlStatusResponse(
        job_id=job.id,
        website_url=job.website_url,
        status=job.status.value,
        urls_discovered=job.urls_discovered,
        blogs_identified=job.blogs_identified,
        blogs_processed=job.blogs_processed,
        blogs_successful=job.blogs_successful,
        blogs_failed=job.blogs_failed,
        remaining=remaining,
        progress_percent=round(progress, 1),
        total_words_extracted=job.total_words_extracted,
        current_url=job.current_url,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        exports_ready=job.status == JobStatus.COMPLETED and bool(job.export_xlsx_path),
    )


@router.get("/{job_id}", response_model=CrawlStatusResponse)
def get_crawl_status(job_id: str, db: Session = Depends(get_db)):
    """GET /api/crawl/{job_id} -- polled by the frontend dashboard (§10, §24)."""
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_status_response(job)


@router.get("/{job_id}/results", response_model=CrawlResultsResponse)
def get_crawl_results(job_id: str, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    """GET /api/crawl/{job_id}/results"""
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    total = db.query(BlogResult).filter(BlogResult.job_id == job_id).count()
    rows = (
        db.query(BlogResult)
        .filter(BlogResult.job_id == job_id)
        .order_by(BlogResult.extraction_date)
        .offset(offset).limit(limit).all()
    )
    return CrawlResultsResponse(
        job_id=job_id, total=total,
        results=[BlogResultOut.model_validate(r) for r in rows],
    )


@router.get("/{job_id}/failed")
def download_failed_urls(job_id: str, db: Session = Depends(get_db)):
    """GET /api/crawl/{job_id}/failed -- downloads failed_urls.csv (§20)."""
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.export_failed_csv_path or not os.path.exists(job.export_failed_csv_path):
        raise HTTPException(status_code=404, detail="Failed-URL export not available yet")
    return FileResponse(job.export_failed_csv_path, filename="failed_urls.csv", media_type="text/csv")


@router.get("/{job_id}/download/excel")
def download_excel(job_id: str, db: Session = Depends(get_db)):
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.export_xlsx_path or not os.path.exists(job.export_xlsx_path):
        raise HTTPException(status_code=404, detail="Excel export not ready yet")
    return FileResponse(
        job.export_xlsx_path,
        filename=os.path.basename(job.export_xlsx_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/download/csv")
def download_csv(job_id: str, db: Session = Depends(get_db)):
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.export_csv_path or not os.path.exists(job.export_csv_path):
        raise HTTPException(status_code=404, detail="CSV export not ready yet")
    return FileResponse(job.export_csv_path, filename=os.path.basename(job.export_csv_path), media_type="text/csv")


@router.post("/{job_id}/resume", response_model=CrawlCreateResponse)
def resume_crawl(job_id: str, db: Session = Depends(get_db)):
    """POST /api/crawl/{job_id}/resume -- §21 resume an interrupted crawl."""
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.PAUSED, JobStatus.FAILED):
        raise HTTPException(status_code=400, detail=f"Job is not resumable (status={job.status.value})")

    job.status = JobStatus.PENDING
    job.error_message = None
    db.commit()

    resume_crawl_job.delay(job.id)
    return CrawlCreateResponse(job_id=job.id, status="pending")


@router.post("/{job_id}/cancel", response_model=CrawlCreateResponse)
def cancel_crawl(job_id: str, db: Session = Depends(get_db)):
    """POST /api/crawl/{job_id}/cancel -- cancels an in-progress crawl."""
    job = db.query(CrawlJob).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Check if the job is in a cancellable state
    if job.status not in (JobStatus.PENDING, JobStatus.DISCOVERING, JobStatus.CRAWLING, JobStatus.PAUSED):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a job with status {job.status.value}")

    job.status = JobStatus.CANCELLED
    db.commit()

    return CrawlCreateResponse(job_id=job.id, status=job.status.value)
