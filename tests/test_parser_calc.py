from pathlib import Path

from app.calc import DEFAULT_SETTINGS, estimate
from app.parser import parse_pdf

SAMPLE = Path(__file__).parent / "sale42.pdf"


def test_parse_sale42():
    sale = parse_pdf(SAMPLE.read_bytes())
    assert sale.sale_no == 42
    assert sale.sale_date == "2026-09-29"
    assert len(sale.grades) == 16
    prices = {g.grade: g.avg_price for g in sale.grades}
    assert prices["AA"] == 340.42 and prices["AB"] == 336.26 and prices["C"] == 305.75
    assert sale.total_avg_price == 299.71


def test_estimate_math():
    s = dict(DEFAULT_SETTINGS, usd_kes=130, green_per_parchment=0.8, cherry_per_parchment=5, deduction_pct=0,
             processing_cost_per_kg_parchment=0)
    e = estimate({"AA": 350, "AB": 330, "C": 310, "PB": 999}, s)
    assert e.avg_usd_per_bag == 330.0  # PB ignored
    assert e.green_kes_per_kg == 858.0  # 330*130/50
    assert e.parchment_kes_per_kg == 686.4  # *0.8
    assert e.parchment_kes_per_50kg == 34320.0
    assert e.cherry_kes_per_kg == 137.28  # /5


def test_estimate_missing_grade_uses_available():
    e = estimate({"AA": 300, "AB": 200}, DEFAULT_SETTINGS)
    assert e.grades_used == ["AA", "AB"] and e.avg_usd_per_bag == 250.0
    assert estimate({"PB": 1}, DEFAULT_SETTINGS) is None


def _sale(no, d, aa, ab, c, bags=(100, 300, 200)):
    return {
        "sale_id": 2025000 + no, "season": 2025, "sale_no": no, "sale_date": d, "total_avg_price": None, "source": "nce",
        "grades": {
            g: {"avg_price": p, "bags": b, "value_usd": p * b * 50}
            for g, p, b in zip(("AA", "AB", "C"), (aa, ab, c), bags)
        },
    }


def test_analysis_basics():
    from app.analysis import analyse

    sales = [_sale(1, "2026-01-06", 400, 380, 340), _sale(2, "2026-01-13", 410, 390, 350),
             _sale(3, "2026-01-20", 420, 400, 360), _sale(5, "2026-02-03", 430, 410, 370)]
    a = analyse(sales, DEFAULT_SETTINGS)
    s = a["summary"]
    assert s["sales_count"] == 4 and s["latest_sale"] == 5
    assert a["gaps"] == ["2025/26 #4"]
    assert s["trend"] == "rising" and s["change_vs_prev_pct"] > 0
    assert s["range_position_pct"] == 100 and s["high"]["sale_no"] == 5 and s["low"]["sale_no"] == 1
    assert a["rows"][3]["ma4"] is not None and a["rows"][2]["ma4"] is None
    assert a["next_sale_band"]["low"] < a["next_sale_band"]["high"]
    mid = [r for r in a["sensitivity"] if r["fx_pct"] == 0][0]["cherry"][1]
    assert mid == a["rows"][-1]["cherry"]  # zero shock reproduces the latest estimate


def test_analysis_empty():
    from app.analysis import analyse

    assert analyse([], DEFAULT_SETTINGS)["empty"] is True
