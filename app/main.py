import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analysis, db, news, scraper
from .calc import DEFAULT_SETTINGS

logging.basicConfig(level=logging.INFO)
POLL_MINUTES = float(os.environ.get("PA_POLL_MINUTES", "30"))
NEWS_HOURS = float(os.environ.get("PA_NEWS_HOURS", "12"))
STATIC = Path(__file__).resolve().parent.parent / "static"

state = {
    "last_check": None, "last_result": None, "error": None,
    "news_last_check": None, "news_result": None, "news_error": None,
}
_sync_lock = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def run_sync():
    """Check the exchange for new sale reports."""
    async with _sync_lock:
        try:
            state["last_result"] = await asyncio.to_thread(scraper.sync)
            state["error"] = None
        except Exception as e:
            state["error"] = str(e)
            logging.exception("sync failed")
        state["last_check"] = _now()
    return state["last_result"]


async def run_news_sync():
    """Backfill older sales from news write-ups (and cross-check recent ones)."""
    async with _sync_lock:
        try:
            state["news_result"] = await asyncio.to_thread(news.sync)
            state["news_error"] = None
        except Exception as e:
            state["news_error"] = str(e)
            logging.exception("news sync failed")
        state["news_last_check"] = _now()
    return state["news_result"]


async def poll_loop():
    await run_sync()
    await run_news_sync()
    last_news = asyncio.get_event_loop().time()
    while True:
        await asyncio.sleep(POLL_MINUTES * 60)
        await run_sync()
        if asyncio.get_event_loop().time() - last_news > NEWS_HOURS * 3600:
            await run_news_sync()
            last_news = asyncio.get_event_loop().time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()


app = FastAPI(title="Coffee Price Analyzer", lifespan=lifespan)


class SettingsIn(BaseModel):
    usd_kes: float = Field(gt=0)
    green_per_parchment: float = Field(gt=0, le=1)
    cherry_per_parchment: float = Field(gt=0)
    deduction_pct: float = Field(ge=0, lt=100)
    processing_cost_per_kg_parchment: float = Field(ge=0)


@app.get("/api/prices")
def prices():
    return {"settings": db.get_settings(), "status": state}


@app.get("/api/analysis")
def get_analysis():
    return analysis.analyse(db.all_sales(), db.get_settings())


@app.get("/api/export.csv")
def export_csv():
    a = analysis.analyse(db.all_sales(), db.get_settings())
    cols = ["season", "sale_no", "date", "AA", "AB", "C", "mix", "estimated", "market_avg", "parchment50", "cherry", "ma4", "ma8", "total_bags", "source"]
    lines = [",".join(cols)]
    for r in a["rows"]:
        lines.append(",".join("" if r.get(c) is None else str(r[c]) for c in cols))
    return Response(
        "\n".join(lines) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=nce_price_history.csv"},
    )


@app.get("/api/settings")
def get_settings():
    return {"settings": db.get_settings(), "defaults": DEFAULT_SETTINGS}


@app.put("/api/settings")
def put_settings(s: SettingsIn):
    db.save_settings(s.model_dump())
    return {"settings": db.get_settings()}


@app.post("/api/refresh")
async def refresh():
    result = await run_sync()
    news_result = await run_news_sync()
    return {"result": result, "news": news_result, "error": state["error"] or state["news_error"]}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
