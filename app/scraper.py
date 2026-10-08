"""Fetch new NCE market reports and store parsed sales."""
import json
import logging
import re
import time

import requests

from . import db
from .parser import parse_pdf

BASE = "https://www.nairobicoffeeexchange.co.ke"
HEADERS = {"User-Agent": "FactoryPriceAnalyzer/1.0 (internal price tracking)"}
log = logging.getLogger("scraper")

# The listing page is a Next.js page; each report is embedded as escaped JSON.
_REPORT = re.compile(r'\\"id\\":\\"(\d+)\\",\\"title\\":\\"(Market Total\s*-?\s*Sale\s*\d+.*?)\\"', re.I)


def list_reports() -> list[tuple[int, str]]:
    r = requests.get(f"{BASE}/market-reports", headers=HEADERS, timeout=30)
    r.raise_for_status()
    seen, out = set(), []
    for rid, title in _REPORT.findall(r.text):
        if rid not in seen:
            seen.add(rid)
            out.append((int(rid), title))
    return out


def fetch_pdf(report_id: int) -> bytes:
    r = requests.get(f"{BASE}/api/market-reports/{report_id}/pdf?download=1", headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.content


def sync() -> dict:
    """Download and parse any report not yet stored. Returns a summary."""
    result = {"new": [], "failed": [], "checked": 0}
    reports = list_reports()
    result["checked"] = len(reports)
    done = db.seen_ok_ids()
    manual = db.manual_report_ids()  # image-only PDFs already transcribed by hand
    for rid, title in sorted(reports):
        if rid in done:
            continue
        if rid in manual:
            db.mark_seen(rid, title, "ok")
            continue
        try:
            sale = parse_pdf(fetch_pdf(rid))
            db.save_sale(sale, rid)
            db.mark_seen(rid, title, "ok")
            result["new"].append(sale.sale_no)
            log.info("Stored %s (sale %s)", title, sale.sale_no)
        except Exception as e:  # keep going; one bad report shouldn't block the rest
            db.mark_seen(rid, title, f"error: {e}"[:200])
            result["failed"].append({"report_id": rid, "title": title, "error": str(e)})
            log.warning("Failed %s: %s", title, e)
        time.sleep(0.5)  # be polite
    return result
