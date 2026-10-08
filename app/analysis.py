"""Market analysis on top of stored sales. All price series are for the AA/AB/C mix estimate."""
import math
from datetime import date

from .calc import BAG_KG, MIX_GRADES, estimate, estimate_from_mix

MAIN_SEASON_MONTHS = {7, 8, 9, 10, 11, 12, 1, 2}  # early/main crop: top grades dominate


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _std(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _slope(ys):
    """Least-squares slope per step."""
    n = len(ys)
    if n < 2:
        return None
    xm, ym = (n - 1) / 2, _mean(ys)
    den = sum((i - xm) ** 2 for i in range(n))
    return sum((i - xm) * (y - ym) for i, y in enumerate(ys)) / den


def _pct(a, b):
    return None if a is None or not b else round((a - b) / b * 100, 2)


def _moving(vals, n):
    out = []
    for i in range(len(vals)):
        w = vals[max(0, i - n + 1) : i + 1]
        out.append(round(_mean(w), 2) if len(w) == n else None)
    return out


def _phase(d: str) -> str:
    return "main" if int(d[5:7]) in MAIN_SEASON_MONTHS else "late"


def season_label(season: int) -> str:
    return f"{season}/{(season + 1) % 100:02d}"


def _calibrate(sales: list[dict]) -> dict:
    """Ratio of the exchange's overall market average to the AA/AB/C mix, by part of the season.

    Lets sales that only state a market average (older news write-ups) be converted to a mix price.
    """
    ratios: dict[str, list[float]] = {"main": [], "late": []}
    for s in sales:
        g = {k: r["avg_price"] for k, r in s["grades"].items() if r.get("avg_price")}
        if s.get("total_avg_price") and all(k in g for k in MIX_GRADES):
            mix = sum(g[k] for k in MIX_GRADES) / 3
            ratios[_phase(s["sale_date"])].append(s["total_avg_price"] / mix)
    allr = ratios["main"] + ratios["late"]
    out = {}
    for ph, rs in ratios.items():
        use = rs if len(rs) >= 3 else allr
        if use:
            sd = _std(use)
            out[ph] = {"ratio": round(_median(use), 4), "n": len(rs), "spread_pct": round(sd / _mean(use) * 100, 1) if sd else None}
    return out


def analyse(sales: list[dict], settings: dict) -> dict:
    """sales: list from db.all_sales(), in date order."""
    cal = _calibrate(sales)
    rows = []
    for s in sales:
        grades = s["grades"]
        prices = {g: r["avg_price"] for g, r in grades.items() if r.get("avg_price")}
        exact = estimate(prices, settings) if all(g in prices for g in MIX_GRADES) else None
        if exact is None and s.get("source") in ("nce", "manual"):
            exact = estimate(prices, settings)  # exchange reports may lack a grade; use what is there
        est, basis = exact, "grades"
        if est is None:
            c = cal.get(_phase(s["sale_date"]))
            if not (c and s.get("total_avg_price")):
                continue
            est = estimate_from_mix(s["total_avg_price"] / c["ratio"], settings, [])
            basis = "market-avg"
        bags_known = all(grades.get(g, {}).get("bags") for g in MIX_GRADES)
        bags = {g: grades[g]["bags"] for g in MIX_GRADES} if bags_known else None
        weighted = None
        if bags and all(g in prices for g in MIX_GRADES):
            tb = sum(bags.values())
            weighted = sum(prices[g] * bags[g] for g in MIX_GRADES) / tb if tb else None
        total_bags = sum(g["bags"] for g in grades.values() if g.get("bags")) if bags_known else None
        total_value = sum(g["value_usd"] for g in grades.values() if g.get("value_usd")) if bags_known else None
        rows.append(
            {
                "sale_id": s["sale_id"],
                "sale_no": s["sale_no"],
                "season": season_label(s["season"]),
                "date": s["sale_date"],
                "source": s.get("source", "nce"),
                "url": s.get("url"),
                "estimated": basis == "market-avg",
                "cherry": est.cherry_kes_per_kg,
                "parchment50": est.parchment_kes_per_50kg,
                "mix": est.avg_usd_per_bag,
                "weighted_mix": round(weighted, 2) if weighted else None,
                "AA": prices.get("AA"),
                "AB": prices.get("AB"),
                "C": prices.get("C"),
                "bags": bags,
                "total_bags": total_bags,
                "total_value": total_value,
                "market_avg": s.get("total_avg_price"),
            }
        )
    if not rows:
        return {"rows": [], "empty": True}

    cherry = [r["cherry"] for r in rows]
    mix = [r["mix"] for r in rows]
    ma4, ma8 = _moving(cherry, 4), _moving(cherry, 8)
    for i, (r, a, b) in enumerate(zip(rows, ma4, ma8)):
        r["ma4"], r["ma8"] = a, b
        r["grade_premium_aa_ab"] = round(r["AA"] - r["AB"], 2) if r["AA"] and r["AB"] else None
        r["grade_discount_ab_c"] = round(r["AB"] - r["C"], 2) if r["AB"] and r["C"] else None
        prev = rows[i - 1] if i else None
        r["change_kes"] = round(r["cherry"] - prev["cherry"], 2) if prev else None
        r["change_pct"] = _pct(r["cherry"], prev["cherry"]) if prev else None

    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    changes = [_pct(rows[i]["mix"], rows[i - 1]["mix"]) for i in range(1, len(rows))]
    vol = _std(changes)
    recent = cherry[-6:]
    slope = _slope(recent)  # KES per kg cherry, per sale
    lo_i, hi_i = cherry.index(min(cherry)), cherry.index(max(cherry))
    rng = max(cherry) - min(cherry)

    if slope is None:
        trend = "unknown"
    elif abs(slope) < 0.01 * _mean(recent):
        trend = "steady"
    else:
        trend = "rising" if slope > 0 else "falling"

    # Indicative next-sale range: last value ± one standard deviation of weekly % moves. Rough, not a forecast model.
    band = None
    if vol is not None:
        drift = (slope or 0) * 0.5  # damp the recent slope so one jump does not dominate
        mid = last["cherry"] + drift
        band = {
            "low": round(mid * (1 - vol / 100), 2),
            "mid": round(mid, 2),
            "high": round(mid * (1 + vol / 100), 2),
            "vol_pct": round(vol, 2),
        }

    # Sensitivity: cherry KES/kg for FX and deduction changes around today's settings
    base_prices = {g: last[g] for g in MIX_GRADES if last.get(g)}
    grid = []
    for fx_d in (-5, -2.5, 0, 2.5, 5):
        line = []
        for ded_d in (-5, 0, 5):
            s2 = dict(settings, usd_kes=settings["usd_kes"] * (1 + fx_d / 100), deduction_pct=settings["deduction_pct"] + ded_d)
            e2 = estimate(base_prices, s2) if base_prices else estimate_from_mix(last["mix"], s2)
            line.append(e2.cherry_kes_per_kg if e2 else None)
        grid.append({"fx_pct": fx_d, "fx": round(settings["usd_kes"] * (1 + fx_d / 100), 2), "cherry": line})

    breakeven = [{"usd_drop_pct": d, "needed_fx": round(settings["usd_kes"] / (1 - d / 100), 2)} for d in (2, 5, 10)]

    # Volume mix of AA/AB/C in the latest sale that reports bags
    share = None
    with_bags = [r for r in rows if r["bags"]]
    if with_bags:
        lb = with_bags[-1]["bags"]
        tb = sum(lb.values()) or 1
        share = {g: round(lb.get(g, 0) / tb * 100, 1) for g in MIX_GRADES}

    # Sale numbers missing inside each season's range
    gaps = []
    by_season: dict[str, set[int]] = {}
    for r in rows:
        by_season.setdefault(r["season"], set()).add(r["sale_no"])
    for sea, nos in by_season.items():
        gaps += [f"{sea} #{n}" for n in range(min(nos), max(nos) + 1) if n not in nos]

    months: dict[str, list[float]] = {}
    for r in rows:
        months.setdefault(r["date"][:7], []).append(r["cherry"])
    monthly = [{"month": m, "avg_cherry": round(_mean(v), 2), "sales": len(v)} for m, v in months.items()]

    wdiff = None
    if last["weighted_mix"]:
        wdiff = round((last["weighted_mix"] - last["mix"]) / last["mix"] * 100, 2)

    position = round((last["cherry"] - min(cherry)) / rng * 100) if rng else 50

    days_since = None
    try:
        days_since = (date.today() - date.fromisoformat(last["date"])).days
    except ValueError:
        pass

    return {
        "empty": False,
        "rows": rows,
        "summary": {
            "latest_sale": last["sale_no"],
            "latest_date": last["date"],
            "days_since_sale": days_since,
            "cherry": last["cherry"],
            "change_vs_prev_pct": _pct(last["cherry"], prev["cherry"]) if prev else None,
            "change_vs_prev_kes": round(last["cherry"] - prev["cherry"], 2) if prev else None,
            "vs_ma4_pct": _pct(last["cherry"], last["ma4"]),
            "vs_ma8_pct": _pct(last["cherry"], last["ma8"]),
            "trend": trend,
            "trend_kes_per_sale": round(slope, 2) if slope is not None else None,
            "high": {"cherry": cherry[hi_i], "sale_no": rows[hi_i]["sale_no"], "date": rows[hi_i]["date"], "estimated": rows[hi_i]["estimated"]},
            "low": {"cherry": cherry[lo_i], "sale_no": rows[lo_i]["sale_no"], "date": rows[lo_i]["date"], "estimated": rows[lo_i]["estimated"]},
            "range_position_pct": position,
            "avg_all": round(_mean(cherry), 2),
            "volatility_pct": round(vol, 2) if vol is not None else None,
            "mix_usd_latest": last["mix"],
            "mix_usd_range": [min(mix), max(mix)],
            "volume_weighted_gap_pct": wdiff,
            "sales_count": len(rows),
            "estimated_count": sum(r["estimated"] for r in rows),
            "first_date": rows[0]["date"],
        },
        "calibration": cal,
        "next_sale_band": band,
        "grade_share_latest": share,
        "sensitivity": grid,
        "breakeven": breakeven,
        "gaps": gaps,
        "monthly": monthly,
        "bag_kg": BAG_KG,
    }
