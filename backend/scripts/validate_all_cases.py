"""
Post-batch validation — Section 8 of the implementation plan.

Confirms:
  1. 20 files exist, correctly named HHG-001.json through HHG-020.json
  2. Every referenced ID exists in TigerGraph
  3. sar.file agrees with FILE_REPORT in next_best_actions.final
  4. pattern_description populated iff pattern == "undocumented"
  5. legitimate verdicts → empty affected_txn_ids, zero exposure_usd, sar.file == false
"""

from __future__ import annotations

import json
import os
import sys
import logging

import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CASES_DIR = os.path.join(os.path.dirname(__file__), "..", "cases")
EXPECTED_CASES = [f"HHG-{i:03d}" for i in range(1, 21)]


def get_connection():
    try:
        conn = tg.TigerGraphConnection(
            host=os.environ.get("TIGERGRAPH_HOST", ""),
            username=os.environ.get("TIGERGRAPH_USERNAME", "tigergraph"),
            password=os.environ.get("TIGERGRAPH_PASSWORD", ""),
            graphname=os.environ.get("TIGERGRAPH_GRAPH_NAME", "FraudInvestigation"),
        )
        try:
            conn.getToken(conn.createSecret())
        except Exception:
            pass
        return conn
    except Exception:
        logger.warning("Could not connect to TigerGraph. ID existence checks will be skipped.")
        return None


def validate_all_cases():
    """Run comprehensive validation on all 20 case answer files."""
    conn = get_connection()
    errors = []
    warnings = []

    print("=" * 70)
    print("ANSWER FILE VALIDATION — 20 Cases")
    print("=" * 70)

    # ── Check 1: File existence ──────────────────────────────────────────
    print("\n--- File Existence ---")
    for case_id in EXPECTED_CASES:
        filepath = os.path.join(CASES_DIR, f"{case_id}.json")
        if os.path.exists(filepath):
            print(f"  ✓ {case_id}.json exists")
        else:
            print(f"  ✗ {case_id}.json MISSING")
            errors.append(f"{case_id}.json missing")

    # ── Check 2–5: Per-file validation ───────────────────────────────────
    print("\n--- Per-Case Validation ---")
    for case_id in EXPECTED_CASES:
        filepath = os.path.join(CASES_DIR, f"{case_id}.json")
        if not os.path.exists(filepath):
            continue

        with open(filepath, "r") as f:
            data = json.load(f)

        case = data.get("case", {})
        sar = data.get("sar", {})
        nba = data.get("next_best_actions", {})

        print(f"\n  [{case_id}] verdict={case.get('verdict')}, pattern={case.get('pattern')}, "
              f"prob={case.get('fraud_probability'):.2f}, exposure=${case.get('exposure_usd', 0):.2f}")

        # Check 2: ID existence in TigerGraph
        if conn:
            # Check affected_txn_ids
            for txn_id in case.get("affected_txn_ids", []):
                try:
                    result = conn.getVerticesById("Transaction", str(txn_id))
                    if not result:
                        errors.append(f"{case_id}: affected_txn_id {txn_id} not found in graph")
                        print(f"    ✗ affected_txn_id {txn_id} NOT FOUND")
                except Exception:
                    warnings.append(f"{case_id}: could not verify txn {txn_id}")

            # Check connected_card_ids
            for card_id in case.get("connected_card_ids", []):
                try:
                    result = conn.getVerticesById("Card", str(card_id))
                    if not result:
                        errors.append(f"{case_id}: connected_card_id {card_id} not found in graph")
                        print(f"    ✗ connected_card_id {card_id} NOT FOUND")
                except Exception:
                    warnings.append(f"{case_id}: could not verify card {card_id}")

            # Check similar_prior_cases
            for prior_id in case.get("similar_prior_cases", []):
                try:
                    result = conn.getVerticesById("ClosedCase", str(prior_id))
                    if not result:
                        errors.append(f"{case_id}: similar_prior_case {prior_id} not found in graph")
                        print(f"    ✗ similar_prior_case {prior_id} NOT FOUND")
                except Exception:
                    warnings.append(f"{case_id}: could not verify case {prior_id}")

        # Check 3: sar.file agrees with FILE_REPORT in final actions
        has_file_report = any(
            a.get("action") == "FILE_REPORT"
            for a in nba.get("final", [])
        )
        sar_file = sar.get("file", False)

        if sar_file and not has_file_report:
            errors.append(f"{case_id}: sar.file=true but FILE_REPORT not in final actions")
            print(f"    ✗ SAR/FILE_REPORT mismatch: sar.file=true but no FILE_REPORT action")
        elif not sar_file and has_file_report:
            errors.append(f"{case_id}: FILE_REPORT in final but sar.file=false")
            print(f"    ✗ SAR/FILE_REPORT mismatch: FILE_REPORT action but sar.file=false")
        else:
            print(f"    ✓ SAR/FILE_REPORT agreement")

        # Check 4: pattern_description iff pattern == "undocumented"
        pattern = case.get("pattern", "")
        pattern_desc = case.get("pattern_description", "")
        if pattern == "undocumented" and not pattern_desc.strip():
            errors.append(f"{case_id}: pattern is 'undocumented' but pattern_description is empty")
            print(f"    ✗ Missing pattern_description for undocumented pattern")
        elif pattern != "undocumented" and pattern_desc.strip():
            errors.append(f"{case_id}: pattern is '{pattern}' but pattern_description is non-empty")
            print(f"    ✗ Unexpected pattern_description for pattern '{pattern}'")
        else:
            print(f"    ✓ pattern_description consistency")

        # Check 5: legitimate verdicts → constraints
        verdict = case.get("verdict", "")
        if verdict == "legitimate":
            if case.get("affected_txn_ids", []):
                errors.append(f"{case_id}: legitimate verdict has non-empty affected_txn_ids")
                print(f"    ✗ Legitimate verdict with affected_txn_ids")
            if case.get("exposure_usd", 0) != 0:
                errors.append(f"{case_id}: legitimate verdict has non-zero exposure_usd")
                print(f"    ✗ Legitimate verdict with exposure_usd={case.get('exposure_usd')}")
            if sar_file:
                errors.append(f"{case_id}: legitimate verdict has sar.file=true")
                print(f"    ✗ Legitimate verdict with SAR filing")
            if not any(msg for msg in errors if case_id in msg and "legitimate" in msg.lower()):
                print(f"    ✓ Legitimate verdict constraints")
        else:
            print(f"    ✓ Non-legitimate verdict (no constraint check needed)")

        # Check: sar narrative content when file=true
        if sar_file:
            narrative = sar.get("narrative", "")
            if not narrative.strip():
                errors.append(f"{case_id}: sar.file=true but narrative is empty")
                print(f"    ✗ Empty SAR narrative")
            elif len(narrative.split(". ")) < 4:
                warnings.append(f"{case_id}: SAR narrative seems short ({len(narrative.split('. '))} sentences)")
                print(f"    ⚠ SAR narrative may be too short")
            else:
                print(f"    ✓ SAR narrative present")

            activity_dates = sar.get("activity_dates", [])
            if len(activity_dates) != 2:
                errors.append(f"{case_id}: sar activity_dates should have exactly 2 entries, got {len(activity_dates)}")
                print(f"    ✗ SAR activity_dates: {len(activity_dates)} entries (expected 2)")
        else:
            # When sar.file=false, all SAR fields should be empty/zero
            if sar.get("narrative", ""):
                errors.append(f"{case_id}: sar.file=false but narrative is non-empty")
            if sar.get("subjects", []):
                errors.append(f"{case_id}: sar.file=false but subjects is non-empty")
            if sar.get("total_amount_usd", 0) != 0:
                errors.append(f"{case_id}: sar.file=false but total_amount_usd is non-zero")

        # Check: written_to_graph
        if not case.get("written_to_graph", False):
            warnings.append(f"{case_id}: written_to_graph is false")
            print(f"    ⚠ Not written to graph")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"  Files checked: {sum(1 for c in EXPECTED_CASES if os.path.exists(os.path.join(CASES_DIR, f'{c}.json')))}/20")
    print(f"  Errors:   {len(errors)}")
    print(f"  Warnings: {len(warnings)}")

    if errors:
        print("\n  ERRORS (must fix before submission):")
        for e in errors:
            print(f"    ✗ {e}")

    if warnings:
        print("\n  WARNINGS (should address if possible):")
        for w in warnings:
            print(f"    ⚠ {w}")

    if not errors:
        print("\n  ✓ ALL VALIDATIONS PASSED — ready for submission!")
    else:
        print(f"\n  ✗ {len(errors)} error(s) found. Fix before submitting.")

    return len(errors) == 0


if __name__ == "__main__":
    success = validate_all_cases()
    sys.exit(0 if success else 1)
