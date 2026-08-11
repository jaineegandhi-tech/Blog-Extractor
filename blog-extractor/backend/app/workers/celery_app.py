from celery import Celery

from app.config import settings

celery_app = Celery(
    "blog_extractor",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=6 * 60 * 60,       # hard cap: 6h per job (large sites)
    task_soft_time_limit=5.5 * 60 * 60,
    worker_prefetch_multiplier=1,       # one job per worker slot at a time
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
)
