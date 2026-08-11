from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api import crawl

app = FastAPI(
    title="Website Blog Extraction Agent API",
    version="1.0.0",
    description="Discovers and extracts blog/article content from a website into Excel/CSV.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your frontend origin in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(crawl.router, prefix="/api")
