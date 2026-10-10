import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .calc import DEFAULT_SETTINGS
from .parser import GradeRow, Sale

DB_PATH = Path(os.environ.get("PA_DB", Path(__file__).resolve().parent.parent / "prices.db"))
MANUAL_FILE = Path(__file__).resolve().parent.parent / "data" / "manual_sales.json"

# Higher wins when two sources describe the same sale.
PRIORITY = {"news": 1, "nce": 2, "manual": 3}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
  sale_id INTEGER PRIMARY KEY,      -- season * 1000 + sale_no (sale numbers restart every October)
  season INTEGER NOT NULL,          -- year the season started, e.g. 2025 for 2025/26
  sale_no INTEGER NOT NULL,
  sale_date TEXT NOT NULL,
  report_id INTEGER,
  total_avg_price REAL,
  source TEXT NOT NULL DEFAULT 'nce',
  url TEXT,
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS grade_prices (
  sale_id INTEGER NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE,
  grade TEXT NOT NULL,
  bags INTEGER, weight_kg INTEGER,
  min_price REAL, max_price REAL, value_usd REAL, avg_price REAL,
  PRIMARY KEY (sale_id, grade)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seen_reports (
  report_id INTEGER PRIMARY KEY,
  title TEXT, status TEXT, checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS seen_posts (
  post_id INTEGER PRIMARY KEY,
  title TEXT, status TEXT, checked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def season_of(d: str) -> int:
    """Coffee season runs October to September; returns the starting year."""
    y = date.fromisoformat(d)
    return y.year if y.month >= 10 else y.year - 1


def sale_id(season: int, sale_no: int) -> int:
    return season * 1000 + sale_no


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _migrate(c):
    """Databases from before seasons/news existed keyed sales by sale_no alone. Rebuild them."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(sales)")}
    if not cols or "sale_id" in cols:
        return
    old_sales = [dict(r) for r in c.execute("SELECT * FROM sales")]
    old_grades = [dict(r) for r in c.execute("SELECT * FROM grade_prices")]
    c.execute("DROP TABLE grade_prices")
    c.execute("DROP TABLE sales")
    c.executescript(SCHEMA)
    for s in old_sales:
        season = season_of(s["sale_date"])
        sid = sale_id(season, s["sale_no"])
        c.execute(
            "INSERT INTO sales(sale_id, season, sale_no, sale_date, report_id, total_avg_price, source) VALUES(?,?,?,?,?,?,?)",
            (sid, season, s["sale_no"], s["sale_date"], s.get("report_id"), s.get("total_avg_price"), s.get("source", "nce")),
        )
        for g in old_grades:
            if g["sale_no"] == s["sale_no"]:
                c.execute(
                    "INSERT INTO grade_prices VALUES(?,?,?,?,?,?,?,?)",
                    (sid, g["grade"], g["bags"], g["weight_kg"], g["min_price"], g["max_price"], g["value_usd"], g["avg_price"]),
                )


def init():
    with conn() as c:
        _migrate(c)
        c.executescript(SCHEMA)
    load_manual()


def manual_items() -> list[dict]:
    return json.loads(MANUAL_FILE.read_text(encoding="utf8")) if MANUAL_FILE.exists() else []


def manual_report_ids() -> set[int]:
    return {m["report_id"] for m in manual_items() if m.get("report_id")}


def load_manual():
    """Load hand-entered sales (e.g. image-only PDFs the parser cannot read)."""
    for item in manual_items():
        sale = Sale(
            sale_no=item["sale_no"],
            sale_date=item["sale_date"],
            total_avg_price=item.get("total_avg_price"),
            grades=[GradeRow(*g) for g in item["grades"]],
        )
        save_sale(sale, item.get("report_id"), source="manual")


def get_settings() -> dict:
    with conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    for r in rows:
        if r["key"] in s:
            s[r["key"]] = json.loads(r["value"])
    return s


def save_settings(new: dict):
    with conn() as c:
        for k, v in new.items():
            if k in DEFAULT_SETTINGS:
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, json.dumps(float(v))),
                )


def save_sale(sale: Sale, report_id: int | None, source: str = "nce", url: str | None = None) -> bool:
    """Store a sale unless a higher-priority source already holds it. Returns True if stored."""
    season = season_of(sale.sale_date)
    sid = sale_id(season, sale.sale_no)
    with conn() as c:
        cur = c.execute("SELECT source FROM sales WHERE sale_id = ?", (sid,)).fetchone()
        if cur and PRIORITY.get(cur["source"], 0) > PRIORITY[source]:
            return False
        c.execute("DELETE FROM sales WHERE sale_id = ?", (sid,))
        c.execute(
            "INSERT INTO sales(sale_id, season, sale_no, sale_date, report_id, total_avg_price, source, url) VALUES(?,?,?,?,?,?,?,?)",
            (sid, season, sale.sale_no, sale.sale_date, report_id, sale.total_avg_price, source, url),
        )
        c.executemany(
            "INSERT INTO grade_prices VALUES(?,?,?,?,?,?,?,?)",
            [
                (sid, g.grade, g.bags, g.weight_kg, g.min_price, g.max_price, g.value_usd, g.avg_price)
                for g in sale.grades
            ],
        )
    return True


def mark_seen(report_id: int, title: str, status: str):
    with conn() as c:
        c.execute(
            "INSERT INTO seen_reports(report_id, title, status) VALUES(?,?,?) "
            "ON CONFLICT(report_id) DO UPDATE SET status = excluded.status, checked_at = CURRENT_TIMESTAMP",
            (report_id, title, status),
        )


def seen_ok_ids() -> set[int]:
    with conn() as c:
        return {r["report_id"] for r in c.execute("SELECT report_id FROM seen_reports WHERE status = 'ok'")}


def get_meta(key: str) -> str | None:
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key = ?", ("meta:" + key,)).fetchone()
    return r["value"] if r else None


def set_meta(key: str, value: str):
    with conn() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("meta:" + key, value),
        )


def reset_seen_posts():
    with conn() as c:
        c.execute("DELETE FROM seen_posts")


def mark_post(post_id: int, title: str, status: str):
    with conn() as c:
        c.execute(
            "INSERT INTO seen_posts(post_id, title, status) VALUES(?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET status = excluded.status, checked_at = CURRENT_TIMESTAMP",
            (post_id, title[:200], status),
        )


def seen_post_ids() -> set[int]:
    with conn() as c:
        return {r["post_id"] for r in c.execute("SELECT post_id FROM seen_posts")}


def all_sales() -> list[dict]:
    """Sales in date order, each with a grade -> row dict."""
    with conn() as c:
        sales = [dict(r) for r in c.execute("SELECT * FROM sales ORDER BY sale_date, sale_id")]
        grades = c.execute("SELECT * FROM grade_prices").fetchall()
    by_sale: dict[int, dict] = {}
    for g in grades:
        by_sale.setdefault(g["sale_id"], {})[g["grade"]] = dict(g)
    for s in sales:
        s["grades"] = by_sale.get(s["sale_id"], {})
    return sales
