"""
Central configuration, loaded from environment variables.
All values have sane local-dev defaults so `docker-compose up` works out of the box.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- Database ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://blog:blog@postgres:5432/blog_extractor",
    )

    # --- Celery / Redis ---
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

    # --- Crawling behavior (§16 ethical crawling, configurable) ---
    REQUEST_DELAY_SECONDS: float = float(os.getenv("REQUEST_DELAY_SECONDS", "0.1"))
    MAX_CONCURRENT_REQUESTS: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "20"))
    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RESPECT_ROBOTS_TXT: bool = os.getenv("RESPECT_ROBOTS_TXT", "true").lower() == "true"
    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    # --- Discovery limits (safety valves for §9 large-website support) ---
    MAX_URLS_TO_DISCOVER: int = int(os.getenv("MAX_URLS_TO_DISCOVER", "20000"))
    MAX_PAGINATION_DEPTH: int = int(os.getenv("MAX_PAGINATION_DEPTH", "500"))

    # --- Extraction ---
    JS_RENDER_WORD_COUNT_THRESHOLD: int = int(
        os.getenv("JS_RENDER_WORD_COUNT_THRESHOLD", "80")
    )  # below this, retry with Playwright
    PLAYWRIGHT_NAV_TIMEOUT_MS: int = int(os.getenv("PLAYWRIGHT_NAV_TIMEOUT_MS", "25000"))

    # --- Storage ---
    EXPORT_DIR: str = os.getenv("EXPORT_DIR", "/data/exports")

    # --- Security (§26 SSRF protection) ---
    BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


settings = Settings()
