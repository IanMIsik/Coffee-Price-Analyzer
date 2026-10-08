import os
import tempfile
from pathlib import Path

import pytest

from app import news
from app.analysis import analyse
from app.calc import DEFAULT_SETTINGS
from app.parser import GradeRow, Sale


def post(title, body, date="2025-10-23T08:00:00"):
    return {"id": 1, "date": date, "link": "http://x", "title": {"rendered": title}, "content": {"rendered": f"<p>{body}</p>"}}


def test_market_average_skips_brokers_and_grades():
    text = ("Nairobi Coffee Exchange sale. New KPCU traded 2,200 bags at an average price of USD 398. "
            "The average price per 50 kg bag was USD 404, equating to KES 160 per kilogram of cherry. "
            "AA grade averaged USD 463.37 per bag.")
    assert news.market_average(text) == 404.0


def test_market_average_with_comma_and_extremes_in_sentence():
    t = "The overall average price reached $313 per 50kg bag, ranging from a minimum of $112 to a maximum of $386 per 50kg bag."
    assert news.market_average(t) == 313.0
    assert news.market_average("Certified lots averaged USD 340 per 50 kg bag, above the market.") is None


def test_grade_averages_parallel_clauses():
    t = ("By grade, AB dominated trading with 3,953 bags worth USD 1.93 million at an average of USD 398, followed by C grade "
         "with 3,070 bags worth USD 1.42 million at an average of USD 374, and AA grade with 1,024 bags at an average of USD 454 per bag. "
         "AA grade averaged USD 463.37 per bag, while AB fetched USD 431.12.")
    g = news.grade_averages(t)
    assert g == {"AB": 398.0, "C": 374.0, "AA": 454.0}
    assert news.grade_averages("AA grade averaged USD 463.37 per bag, while AB fetched USD 431.12.") == {"AA": 463.37, "AB": 431.12}
    # a broker's price is not a grade average
    assert news.grade_averages("First Cup Coffee Ltd bought 10 bags of grade AB at an average price of USD 397.") == {}


def test_parse_post_title_date_and_filters():
    p = post("Nairobi Coffee Exchange Sale 3 Results (October 22nd, 2025)",
             "Nairobi Coffee Exchange sale. The average price per 50 kg bag was USD 404.")
    ns = news.parse_post(p)
    assert (ns.sale_no, ns.sale_date, ns.market_avg) == (3, "2025-10-22", 404.0)
    # no sale number in the title -> skipped (could be a retrospective)
    assert news.parse_post(post("Big Volumes, Better Prices", "Nairobi Coffee Exchange up to Sale 11, average price USD 220 per bag.")) is None
    # not a sale day -> skipped
    assert news.parse_post(post("Nairobi Coffee Exchange Sale 5 Results (November 7, 2025)", "NCE. Average price USD 390 per bag.")) is None


def test_renumber_fixes_typos_by_date():
    mk = lambda no, d: news.NewsSale(no, d, 300.0)
    a = news.renumber([mk(30, "2025-07-08"), mk(30, "2025-07-15"), mk(32, "2025-07-22")])
    assert [s.sale_no for s in a] == [30, 31, 32]
    b = news.renumber([mk(4, "2025-10-28"), mk(2, "2025-11-04"), mk(6, "2025-11-11")])
    assert [s.sale_no for s in b] == [4, 5, 6]


@pytest.fixture
def tmpdb(monkeypatch):
    from app import db
    d = tempfile.mkdtemp()
    monkeypatch.setattr(db, "DB_PATH", Path(d) / "t.db")
    monkeypatch.setattr(db, "MANUAL_FILE", Path(d) / "none.json")
    db.init()
    return db


def test_season_key_and_source_priority(tmpdb):
    db = tmpdb
    assert db.season_of("2025-07-08") == 2024 and db.season_of("2025-10-07") == 2025 and db.season_of("2026-09-29") == 2025
    row = lambda p: GradeRow("AA", 1, 1, 1, 1, 1, p)
    # same sale number in two different seasons must not collide
    assert db.save_sale(Sale(30, "2025-07-08", [row(300)], 297.0), None, "news")
    assert db.save_sale(Sale(30, "2026-07-08", [row(400)], 330.0), 5, "nce")
    assert len(db.all_sales()) == 2
    # the exchange's own report replaces a news entry but not vice versa
    assert db.save_sale(Sale(30, "2026-07-08", [row(401)], 331.0), None, "news") is False
    assert [s for s in db.all_sales() if s["season"] == 2025][0]["grades"]["AA"]["avg_price"] == 400


def test_estimated_rows_use_calibrated_ratio():
    def full(no, d, aa, ab, c, total):
        return {"sale_id": 2025000 + no, "season": 2025, "sale_no": no, "sale_date": d, "total_avg_price": total, "source": "nce",
                "grades": {g: {"avg_price": p, "bags": 10, "value_usd": p * 500} for g, p in zip(("AA", "AB", "C"), (aa, ab, c))}}
    sales = [full(i, f"2026-07-{7 + 7 * (i - 1):02d}", 400, 380, 360, 380 * 0.92) for i in range(1, 4)]  # market avg = 0.92 x mix
    news_sale = {"sale_id": 2024030, "season": 2024, "sale_no": 30, "sale_date": "2025-07-15", "total_avg_price": 340.0, "source": "news",
                 "grades": {"AA": {"avg_price": 360.0, "bags": None, "value_usd": None}}}
    a = analyse([news_sale] + sales, DEFAULT_SETTINGS)
    est = a["rows"][0]
    assert est["estimated"] is True and abs(est["mix"] - 340 / 0.92) < 0.01
    assert est["season"] == "2024/25" and a["summary"]["estimated_count"] == 1
    assert all(not r["estimated"] for r in a["rows"][1:])


def test_new_season_first_sale_rolls_over(tmpdb):
    """Sale 1 of 2026/27 must not collide with Sale 1 of 2025/26 and must label the new season."""
    db = tmpdb
    row = lambda g, p: GradeRow(g, 100, 6000, p - 50, p + 50, p * 120, p)
    mk = lambda no, d, k: Sale(no, d, [row("AA", 340 + k), row("AB", 330 + k), row("C", 300 + k)], 310.0 + k)
    assert db.save_sale(mk(1, "2025-10-07", 0), None, "nce")
    assert db.save_sale(mk(42, "2026-09-29", 5), None, "nce")
    assert db.save_sale(mk(1, "2026-10-13", 20), None, "nce")      # first sale of the new season
    sales = db.all_sales()
    assert [s["season"] for s in sales] == [2025, 2025, 2026]
    a = analyse(sales, DEFAULT_SETTINGS)
    assert a["summary"]["latest_date"] == "2026-10-13" and a["rows"][-1]["season"] == "2026/27"
    assert a["rows"][-1]["change_pct"] > 0
