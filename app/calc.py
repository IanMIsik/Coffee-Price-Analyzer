"""Price math: NCE grade averages -> KES per kg of cherry."""
from dataclasses import dataclass

BAG_KG = 50.0
MIX_GRADES = ("AA", "AB", "C")

# Placeholders: tune these to your factory's actual figures on the Settings panel.
DEFAULT_SETTINGS = {
    "usd_kes": 129.0,                 # KES per 1 USD
    "green_per_parchment": 0.80,      # kg clean (green) coffee from 1 kg parchment
    "cherry_per_parchment": 5.5,      # kg cherry needed for 1 kg parchment
    "deduction_pct": 10.0,            # % of gross: marketing, commission, levies, etc.
    "processing_cost_per_kg_parchment": 0.0,  # KES/kg parchment: milling, transport
}


@dataclass
class Estimate:
    avg_usd_per_bag: float       # simple average of AA, AB, C (USD / 50 kg clean)
    grades_used: list[str]
    green_kes_per_kg: float
    parchment_kes_per_50kg: float
    parchment_kes_per_kg: float
    cherry_kes_per_kg: float


def estimate(grade_prices: dict[str, float], s: dict) -> Estimate | None:
    """grade_prices: grade -> USD per 50 kg average. Returns None if no mix grade is present."""
    used = [g for g in MIX_GRADES if grade_prices.get(g)]
    if not used:
        return None
    return estimate_from_mix(sum(grade_prices[g] for g in used) / len(used), s, used)


def estimate_from_mix(avg_usd: float, s: dict, used: list[str] | None = None) -> Estimate:
    """Cherry/parchment prices from a mix price (USD per 50 kg clean coffee)."""
    green_kes_kg = avg_usd * s["usd_kes"] / BAG_KG
    # Gross value of 1 kg parchment = green yield * green price, less % deductions and per-kg cost.
    parch_kg = (
        s["green_per_parchment"] * green_kes_kg * (1 - s["deduction_pct"] / 100)
        - s["processing_cost_per_kg_parchment"]
    )
    return Estimate(
        avg_usd_per_bag=round(avg_usd, 2),
        grades_used=used or [],
        green_kes_per_kg=round(green_kes_kg, 2),
        parchment_kes_per_50kg=round(parch_kg * BAG_KG, 2),
        parchment_kes_per_kg=round(parch_kg, 2),
        cherry_kes_per_kg=round(parch_kg / s["cherry_per_parchment"], 2),
    )
