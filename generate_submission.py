#!/usr/bin/env python3
"""
Generate submission.jsonl — 30 (merchant, trigger[, customer]) compositions.

Usage:
    OPENAI_API_KEY=sk-... python generate_submission.py

Outputs submission.jsonl with one JSON line per test pair.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("gen")

DATASET = Path(__file__).parent / "dataset"
OUTPUT = Path(__file__).parent / "submission.jsonl"

# ---------------------------------------------------------------------------
# Load dataset
# ---------------------------------------------------------------------------

def load_dataset() -> tuple[dict, dict, dict, dict]:
    categories: dict[str, dict] = {}
    for f in (DATASET / "categories").glob("*.json"):
        data = json.loads(f.read_text())
        categories[data["slug"]] = data

    merchants_raw = json.loads((DATASET / "merchants_seed.json").read_text())
    merchants = {m["merchant_id"]: m for m in merchants_raw["merchants"]}

    customers_raw = json.loads((DATASET / "customers_seed.json").read_text())
    customers = {c["customer_id"]: c for c in customers_raw["customers"]}

    triggers_raw = json.loads((DATASET / "triggers_seed.json").read_text())
    triggers = {t["id"]: t for t in triggers_raw["triggers"]}

    return categories, merchants, customers, triggers


# ---------------------------------------------------------------------------
# Test pair definitions (30 total)
# ---------------------------------------------------------------------------
# Format: (test_id, trigger_id, [customer_id or None])

TEST_PAIRS = [
    # ── DENTISTS ──────────────────────────────────────────────────────────
    ("T01", "trg_001_research_digest_dentists",      None),
    ("T02", "trg_002_compliance_dci_radiograph",     None),
    ("T03", "trg_003_recall_due_priya",              "c_001_priya_for_m001"),
    ("T04", "trg_004_perf_dip_bharat",               None),
    ("T05", "trg_005_renewal_due_bharat",            None),
    ("T06", "trg_022_cde_webinar_dentists",          None),
    ("T07", "trg_023_competitor_opened_dentist",     None),

    # ── SALONS ────────────────────────────────────────────────────────────
    ("T08", "trg_006_festival_diwali",               None),
    ("T09", "trg_007_bridal_followup_kavya",         "c_005_kavya_for_m003"),
    ("T10", "trg_008_curious_ask_studio11",          None),
    ("T11", "trg_009_winback_glamour",               None),
    ("T12", "trg_025_dormancy_glamour",              None),

    # ── RESTAURANTS ───────────────────────────────────────────────────────
    ("T13", "trg_010_ipl_match_delhi",               None),
    ("T14", "trg_011_review_theme_late_delivery",    None),
    ("T15", "trg_012_milestone_mylari",              None),
    ("T16", "trg_013_corporate_thali_planning",      None),

    # ── GYMS ──────────────────────────────────────────────────────────────
    ("T17", "trg_014_seasonal_acquisition_dip_powerhouse", None),
    ("T18", "trg_015_winback_rashmi",                "c_010_rashmi_for_m007"),
    ("T19", "trg_016_kids_yoga_program_drafting",    None),
    ("T20", "trg_017_kids_yoga_trial_followup_karthik", "c_012_karthik_jr_for_m008"),
    ("T21", "trg_024_perf_spike_zen",                None),

    # ── PHARMACIES ────────────────────────────────────────────────────────
    ("T22", "trg_018_supply_atorvastatin_recall",    None),
    ("T23", "trg_019_chronic_refill_grandfather",    "c_013_grandfather_for_m009"),
    ("T24", "trg_020_summer_demand_shift",           None),
    ("T25", "trg_021_unverified_gbp_sunrise",        None),

    # ── ADDITIONAL COVERAGE (cross-category / edge cases) ─────────────────
    # T26: Dr. Meera — curious ask (no explicit trigger, using dormant pattern)
    ("T26", "trg_025_dormancy_glamour",              None),   # repurposed for salon dormant
    # T27: Mylari restaurant — review theme positive / milestone imminent
    ("T27", "trg_012_milestone_mylari",              None),   # second angle
    # T28: Zen Yoga — perf spike + kids yoga combined angle
    ("T28", "trg_024_perf_spike_zen",                None),
    # T29: Apollo Pharmacy — seasonal demand shift (2nd angle)
    ("T29", "trg_020_summer_demand_shift",           None),
    # T30: SK Pizza — review theme with IPL context
    ("T30", "trg_010_ipl_match_delhi",               None),
]

# T26–T30 need variant context overrides to avoid being exact duplicates
_VARIANT_OVERRIDES: dict[str, dict] = {
    "T26": {"alt_merchant": "m_003_studio11_salon_hyderabad"},
    "T27": {"hint": "Second angle: use milestone_imminent framing + social proof"},
    "T28": {"hint": "Combine perf spike with kids yoga program launch context"},
    "T29": {"hint": "Focus on antifungal +45% demand, recommend specific shelf action"},
    "T30": {"hint": "Frame IPL match + late delivery review together for urgency"},
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def run() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Import here so we fail early if packages missing
    from bot import compose as _compose

    cats, merchants, customers, triggers = load_dataset()

    lines: list[str] = []
    failed: list[str] = []

    for idx, (test_id, trigger_id, customer_id) in enumerate(TEST_PAIRS, 1):
        trigger = triggers.get(trigger_id)
        if not trigger:
            logger.warning("%s: trigger %s not found — skipping", test_id, trigger_id)
            failed.append(test_id)
            continue

        # Allow variant merchant override for T26+
        override = _VARIANT_OVERRIDES.get(test_id, {})
        merchant_id = override.get("alt_merchant") or trigger.get("merchant_id", "")

        merchant = merchants.get(merchant_id)
        if not merchant:
            logger.warning("%s: merchant %s not found — skipping", test_id, merchant_id)
            failed.append(test_id)
            continue

        category = cats.get(merchant.get("category_slug", ""))
        if not category:
            logger.warning("%s: category not found — skipping", test_id)
            failed.append(test_id)
            continue

        customer = customers.get(customer_id) if customer_id else None

        # Inject hint into trigger payload for variant pairs
        if override.get("hint"):
            trigger = {**trigger, "payload": {**trigger.get("payload", {}), "_hint": override["hint"]}}

        logger.info("[%d/30] %s — %s → %s", idx, test_id, merchant_id, trigger_id)

        try:
            result = _compose(
                category=category,
                merchant=merchant,
                trigger=trigger,
                customer=customer,
            )
        except Exception as exc:
            logger.error("%s: composition failed: %s", test_id, exc)
            failed.append(test_id)
            continue

        if not result.get("body"):
            logger.warning("%s: empty body returned", test_id)
            failed.append(test_id)
            continue

        record = {
            "test_id": test_id,
            "merchant_id": merchant_id,
            "trigger_id": trigger_id,
            "customer_id": customer_id,
            **result,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
        logger.info("  ✓ %s  CTA=%s  send_as=%s", test_id, result.get("cta"), result.get("send_as"))

        # Rate limiting: avoid hitting API too fast
        if idx < len(TEST_PAIRS):
            time.sleep(0.5)

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Done — %d/%d written to %s", len(lines), len(TEST_PAIRS), OUTPUT)
    if failed:
        logger.warning("Failed: %s", ", ".join(failed))


if __name__ == "__main__":
    run()
