"""Backfill older sales from Kilimo News auction write-ups (the exchange site only publishes recent reports).

News posts are prose, so extraction is best-effort: every sale gets the overall market average when the post states it,
and AA / AB / C averages when the post states them. Only numbers are stored, never article text.
"""
import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests

from . import db
from .parser import GradeRow, Sale

API = "https://kilimonews.co.ke/wp-json/wp/v2/posts"
HEADERS = {"User-Agent": "FactoryPriceAnalyzer/1.0 (internal price tracking)"}
START = "2025-06-25T00:00:00"  # roughly "up to last year", plus the tail of the previous season
log = logging.getLogger("news")

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}

# A 3-digit USD amount ("USD 404", "$313.50"), not part of a longer number like "USD 1,872,370".
_PRICE = r"(?:USD|US\$|\$)\s?(\d{3}(?:\.\d{1,2})?)(?!\d|,\d)"

# Words that mean a price belongs to a broker, buyer, lot or sub-group rather than the whole market or a grade.
_ENTITY = re.compile(
    r"\b(lots?|factory|FCS|co-?operative|brokers?|buyers?|ltd|limited|union|agency|marketing|kpcu|alliance|kipkelion|"
    r"county|certified|uncertified|certifications?|sustainability|credentials)\b",
    re.I,
)
_NOT_MARKET = re.compile(r"\b(highest|lowest|top|best|maximum|minimum)\b", re.I)
_ANY_GRADE = re.compile(r"\b(AA|AB)\b|\bC[- ]grade\b|\bgrade[- ]C\b")
_GRADE_TOKENS = {
    "AA": r"\bAA\b",
    "AB": r"\bAB\b",
    "C": r"\bC[- ]grade\b|\bgrade[- ]C\b",
}
_CLAUSE_SPLIT = re.compile(r",?\s*\b(?:while|followed by|whereas)\s+|;|,\s+and\s+(?=AA\b|AB\b|C[- ]grade|grade[- ]C)")


@dataclass
class NewsSale:
    sale_no: int
    sale_date: str
    market_avg: float | None
    grades: dict[str, float] = field(default_factory=dict)  # grade -> USD per 50 kg
    url: str = ""
    title: str = ""


def to_text(raw: str) -> str:
    t = re.sub(r"(?s)<(script|style).*?</\1>", "", raw)
    t = re.sub(r"</(p|li|h\d|div|tr)>|<br\s*/?>", "\n", t)
    t = re.sub(r"</t[dh]>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]


def parse_date(title: str, text: str, post_date: str) -> str:
    """Sale date from the title, else 'held on ...', else the Tuesday before the post."""
    m = re.search(r"\(\s*([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", title)
    if m and m.group(1).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    head = text[:1500]
    m = re.search(r"(?:held|took place|conducted)[^.]{0,40}?(?:on\s+)?(?:\w+day,?\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", head)
    if m and m.group(1).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    m = re.search(r"(?:held|took place|conducted)[^.]{0,40}?(?:on\s+)?(?:\w+day,?\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})", head)
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    d = datetime.fromisoformat(post_date[:10]).date() - timedelta(days=1)
    return (d - timedelta(days=(d.weekday() - 1) % 7)).isoformat()  # most recent Tuesday


def market_average(text: str) -> float | None:
    """First 'average ... USD n per 50 kg' that is not about a grade, broker, buyer, lot or certified coffee."""
    for sent in _sentences(text[:6000]):
        m = re.search(r"averag\w*[^$]{0,60}?" + _PRICE, sent, re.I)
        if not m:
            continue
        prefix = sent[: m.start()]
        season_best = re.search(r"highest\s+$", prefix, re.I) and re.search(r"season so far", sent, re.I)
        if _ANY_GRADE.search(prefix) or _ENTITY.search(prefix) or (_NOT_MARKET.search(prefix) and not season_best):
            continue
        if not re.search(r"\bper\b|\bbag\b|50\s?-?\s?kg", sent, re.I):
            continue
        v = float(m.group(1))
        if 150 <= v <= 700:
            return v
    return None


def grade_averages(text: str) -> dict[str, float]:
    """Grade averages stated explicitly ('AA averaged USD 463'), including a parallel clause right after one."""
    out: dict[str, float] = {}
    for sent in _sentences(text[:8000]):
        explicit_before = False
        for clause in _CLAUSE_SPLIT.split(sent):
            hits = [g for g, p in _GRADE_TOKENS.items() if re.search(p, clause)]
            m = re.search(r"averag\w*\s*(?:price\s*)?(?:of\s*|at\s*)?" + _PRICE, clause, re.I)
            if len(hits) != 1:
                explicit_before = explicit_before and bool(m)
                continue
            g = hits[0]
            if _ENTITY.search(clause):  # a broker's, buyer's or lot's price, not the grade average
                explicit_before = False
                continue
            if not m and explicit_before and not _NOT_MARKET.search(clause):  # 'AA averaged 463, while AB fetched 431'
                m = re.search(r"\b(?:fetch\w*|at)\s+" + _PRICE, clause, re.I)
            if m and g not in out and 150 <= float(m.group(1)) <= 700:
                out[g] = float(m.group(1))
            explicit_before = bool(m)
    return out


def parse_post(post: dict) -> NewsSale | None:
    title = html.unescape(re.sub(r"<[^>]+>", "", post["title"]["rendered"]))
    text = to_text(post["content"]["rendered"])
    if not re.search(r"Nairobi Coffee Exchange|\bNCE\b", title + " " + text[:1500]):
        return None
    # Only posts that name the sale in the title: headline-only posts are too easy to misread
    # (retrospectives like "up to Sale 27" would look like a sale write-up).
    m = re.search(r"\bSale\s*(?:No\.?\s*)?(\d{1,2})\b", title)
    if not m:
        return None
    avg = market_average(text)
    grades = grade_averages(text)
    if avg is None and not grades:
        return None
    sale_date = parse_date(title, text, post["date"])
    if date.fromisoformat(sale_date).weekday() not in (1, 2):  # sales are held on Tuesdays (rarely Wednesdays)
        return None
    return NewsSale(
        sale_no=int(m.group(1)),
        sale_date=sale_date,
        market_avg=avg,
        grades=grades,
        url=post.get("link", ""),
        title=title,
    )


def renumber(sales: list[NewsSale]) -> list[NewsSale]:
    """Titles sometimes carry a typo'd sale number. Within a season, numbers must rise with the date."""
    by_season: dict[int, list[NewsSale]] = {}
    for s in sales:
        by_season.setdefault(db.season_of(s.sale_date), []).append(s)
    for items in by_season.values():
        items.sort(key=lambda s: s.sale_date)
        prev = None
        for s in items:
            if prev and s.sale_date != prev.sale_date and s.sale_no <= prev.sale_no:
                weeks = max(1, round((date.fromisoformat(s.sale_date) - date.fromisoformat(prev.sale_date)).days / 7))
                s.sale_no = prev.sale_no + weeks
            prev = s
    return sales


def fetch_posts(after: str = START) -> list[dict]:
    posts, page = [], 1
    while True:
        r = requests.get(
            API,
            params={"after": after, "per_page": 100, "page": page, "orderby": "date", "order": "asc",
                    "_fields": "id,date,link,title,content"},
            headers=HEADERS, timeout=90,
        )
        if r.status_code == 400:  # past the last page
            break
        r.raise_for_status()
        posts += r.json()
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
        time.sleep(0.5)
    return posts


def to_sale(ns: NewsSale) -> Sale:
    """Rows: the grades the post states, so the mix is exact only when AA, AB and C are all present."""
    rows = [GradeRow(g, None, None, None, None, None, p) for g, p in ns.grades.items()]
    return Sale(sale_no=ns.sale_no, sale_date=ns.sale_date, grades=rows, total_avg_price=ns.market_avg)


def sync() -> dict:
    seen = db.seen_post_ids()
    posts = [p for p in fetch_posts() if p["id"] not in seen]
    parsed: list[tuple[dict, NewsSale]] = []
    for p in posts:
        ns = parse_post(p)
        if ns is None:
            db.mark_post(p["id"], re.sub(r"<[^>]+>", "", p["title"]["rendered"]), "skip")
        else:
            parsed.append((p, ns))
    renumber([ns for _, ns in parsed])
    # Several posts can cover one sale (e.g. a follow-up analysis): prefer a "Results" post, then the earliest.
    best: dict[int, tuple[dict, NewsSale, tuple]] = {}
    for p, ns in parsed:
        key = db.sale_id(db.season_of(ns.sale_date), ns.sale_no)
        score = ("Results" in ns.title, ns.market_avg is not None, -int(p["date"][:10].replace("-", "")))
        if key not in best or score > best[key][2]:
            best[key] = (p, ns, score)
    stored = []
    for _, ns, _ in best.values():
        if db.save_sale(to_sale(ns), None, source="news", url=ns.url):
            stored.append(f"{ns.sale_date} #{ns.sale_no}")
    for p, ns in parsed:
        db.mark_post(p["id"], ns.title, "ok")
    return {"posts_checked": len(posts), "sales_found": len(best), "stored": sorted(stored)}
