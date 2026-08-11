# Website Blog Extraction Agent

Paste a website URL → the agent discovers every blog/article on the site → extracts
structured content for each one → hands you Excel + CSV files.

This is a real, working implementation (verified with a passing unit test suite — see
[Testing](#testing)), not a mockup. It has **not** been run against a live public website
from inside this environment — I built and unit-tested it here, but a live end-to-end
crawl needs to happen on infrastructure with open internet access (this build environment's
network is locked to package registries only). Run it locally with the steps below to
crawl a real site.

## Architecture

```
Browser ──▶ Next.js frontend (port 3000)
              │  POST /api/crawl, GET /api/crawl/{id} (polled every 2s)
              ▼
           FastAPI backend (port 8000) ──▶ Postgres (jobs, URLs, results, failures)
              │  enqueues job
              ▼
           Celery worker ──▶ Redis (broker)
              │
              ├─ Discovery: sitemap.xml / sitemap-index (recursive) → falls back to
              │  homepage/nav/footer crawl + pagination + RSS if sitemap is thin
              ├─ Classification: URL heuristics + JSON-LD/og:type/paragraph-density
              │  scoring, so tag/category/login/cart pages get excluded
              ├─ Fetch: async HTTP first; auto-falls back to headless Playwright
              │  when content looks JS-gated (React/Next.js/Vue/Angular sites)
              ├─ Extract: DOM-based main-content isolation (<article>/<main>/density),
              │  rebuilt into [H1]/[H2]/[H3]-tagged structured text, split into
              │  Introduction / Main Content / Conclusion / FAQ, cross-checked
              │  against trafilatura when the DOM pass comes up too short
              └─ Export: streamed openpyxl (write-only mode) + csv module, so
                 multi-thousand-row jobs don't spike memory
```

Every discovered URL is a row in Postgres with a status (`queued` → `processing` →
`success`/`failed`/`skipped`). That's what makes **resume** simple and correct: resuming
a job just re-queues rows that never reached a terminal state — nothing is recomputed,
nothing is duplicated.

## Project layout

```
blog-extractor/
├── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, database.py, models.py, schemas.py
│   │   ├── api/crawl.py              # REST endpoints
│   │   ├── services/                 # url_utils, robots, sitemap, discovery,
│   │   │                             # classifier, fetcher, extractor, exporter
│   │   └── workers/                  # celery_app.py, tasks.py
│   ├── tests/                        # 25 passing unit tests
│   └── requirements.txt
├── frontend/
│   ├── app/page.tsx                  # URL input → progress dashboard → downloads
│   └── lib/api.ts                    # typed API client
└── README.md
```

## Quick start (Docker Compose — recommended)

```bash
git clone <this project> && cd blog-extractor
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend/API docs (Swagger): http://localhost:8000/docs
- Enter a URL, click **Start Blog Extraction**, watch the live dashboard, download
  Excel/CSV/failed-URLs when it finishes.

First build takes a few minutes (Playwright downloads Chromium inside the backend image).

## Local development (without Docker)

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium --with-deps
# Postgres + Redis must be running locally, or point DATABASE_URL/REDIS_URL
# at hosted instances via a .env file (see .env.example)
uvicorn app.main:app --reload
```

**Celery worker** (separate terminal, same venv):
```bash
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Configuration

All crawling behavior is environment-driven (`backend/.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `REQUEST_DELAY_SECONDS` | 0.5 | Delay between requests (§16 ethical crawling) |
| `MAX_CONCURRENT_REQUESTS` | 8 | Concurrency cap per job |
| `MAX_RETRIES` | 3 | Retries before a URL is marked permanently failed |
| `RESPECT_ROBOTS_TXT` | true | Honor robots.txt disallow rules |
| `MAX_URLS_TO_DISCOVER` | 20000 | Safety cap for very large sites |
| `JS_RENDER_WORD_COUNT_THRESHOLD` | 80 | Below this word count, retry with Playwright |

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/crawl` | Start a job. Body: `{"url": "https://example.com"}` → `{job_id, status}` |
| GET | `/api/crawl/{job_id}` | Poll status/progress counters |
| GET | `/api/crawl/{job_id}/results` | Paginated extracted results (`?limit=&offset=`) |
| GET | `/api/crawl/{job_id}/download/excel` | Download the `.xlsx` |
| GET | `/api/crawl/{job_id}/download/csv` | Download the `.csv` |
| GET | `/api/crawl/{job_id}/failed` | Download `failed_urls.csv` |
| POST | `/api/crawl/{job_id}/resume` | Resume a paused/failed job without losing progress |

Interactive docs (request/response schemas) are auto-generated at `/docs` once the
backend is running.

## Testing

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

25 tests cover URL normalization/dedup, SSRF blocking, sitemap-index recursion,
blog-vs-non-blog classification, article/heading/FAQ/conclusion extraction, and
Excel/CSV export — all passing. Two categories are deliberately **not** unit-tested
here because they require live network/browser access: the discovery crawler's actual
HTTP behavior against a real site, and the Playwright rendering path. Test them by
running `docker compose up` and pointing the app at a real, low-traffic site you're
authorized to crawl (e.g. your own blog, or a small test site) — watch the dashboard
and verify Excel output. Recommended test targets: your own staging blog, or a small
public blog you own; **do not** load-test third-party sites you don't control.

## Production deployment notes

- Swap `docker-compose.yml`'s single Postgres/Redis containers for managed services
  (RDS/Cloud SQL, ElastiCache/Memorystore) and drop the `depends_on` healthchecks.
- Run `celery -A app.workers.celery_app worker --concurrency=N` on dedicated worker
  nodes, scaled by queue depth, separate from the API nodes.
- Put the `EXPORT_DIR` volume on shared/object storage (S3 + presigned URLs) instead
  of local disk if you run multiple backend replicas, so any replica can serve a
  download.
- Tighten `CORSMiddleware` `allow_origins` to your real frontend domain.
- Set `RESPECT_ROBOTS_TXT=true` (default) and keep `REQUEST_DELAY_SECONDS`/
  `MAX_CONCURRENT_REQUESTS` conservative — this is a real crawler hitting real
  third-party servers.

## Known simplifications vs. the full spec (flagged honestly)

- **No Alembic migrations yet** — `init_db()` calls `create_all()`. Fine for v1;
  add Alembic before you need to evolve the schema without dropping data.
- **One Celery task per job** (not one task per URL) — internal `asyncio.Semaphore`
  controls concurrency instead of Celery-level fan-out. This was a deliberate choice
  (see comment in `tasks.py`) to make rate-limiting exact and keep Celery's job simply
  "one job = one worker slot." Trade-off: a single job doesn't parallelize across
  multiple worker machines. If you need that, shard by discovered-URL-id and reintroduce
  per-URL tasks with a Celery chord.
- **Category/subcategory** are populated from `article:section`/JSON-LD when the site
  provides them; there's no separate category-inference model.
- **Infinite scroll** is handled by a bounded scroll-and-wait inside the Playwright
  fallback (`fetcher.py`), not full infinite-scroll exhaustion — sufficient for most
  blog index pages, which are more commonly paginated than infinite-scrolled anyway.
