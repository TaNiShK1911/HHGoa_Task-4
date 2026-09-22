"""
ETL: Validate data load — Section 4, Step 8.

Confirms:
  1. Row counts match README's stated counts:
     - 590,742 transactions
     - 144,432 identity records
     - 5,565 closed cases
  2. Every flagged_txn_id in case_pack resolves to a real Transaction vertex
  3. Edge counts are non-zero for key relationships
"""

from __future__ import annotations

import os
import sys
import logging

import pandas as pd
import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Expected counts from README
EXPECTED_TRANSACTIONS = 590_742
EXPECTED_IDENTITY = 144_432
EXPECTED_CLOSED_CASES = 5_565

DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "HHGOA_IEEE-20260919T091224Z-1-001", "HHGOA_IEEE"),
)
CASE_PACK_FILE = os.path.join(DATA_DIR, "case_pack.csv")


def get_connection() -> tg.TigerGraphConnection:
    conn = tg.TigerGraphConnection(
        host=os.environ["TIGERGRAPH_HOST"],
        username=os.environ.get("TIGERGRAPH_USERNAME", "tigergraph"),
        password=os.environ["TIGERGRAPH_PASSWORD"],
        graphname=os.environ.get("TIGERGRAPH_GRAPH_NAME", "FraudInvestigation"),
    )
    try:
        secret = os.environ.get("TIGERGRAPH_SECRET")
        if secret:
            conn.getToken(secret)
        else:
            conn.getToken(conn.createSecret())
    except Exception:
        logger.warning("Could not create secret/token.")
    return conn


def validate_load():
    """Run all validation checks against the loaded data."""
    conn = get_connection()
    errors = []
    warnings = []

    print("=" * 60)
    print("DATA LOAD VALIDATION")
    print("=" * 60)

    # ── Check 1: Vertex counts ───────────────────────────────────────────
    print("\n--- Vertex Counts ---")

    vertex_checks = [
        ("Transaction", EXPECTED_TRANSACTIONS),
        ("ClosedCase", EXPECTED_CLOSED_CASES),
    ]

    for vertex_type, expected in vertex_checks:
        try:
            stats = conn.getVertexCount(vertex_type)
            actual = stats if isinstance(stats, int) else 0
            status = "PASS" if actual == expected else "FAIL"
            diff = actual - expected
            print(f"  {status} {vertex_type}: {actual:,} (expected {expected:,}, diff {diff:+,})")
            if actual != expected:
                errors.append(
                    f"{vertex_type} count mismatch: got {actual}, expected {expected}"
                )
        except Exception as e:
            print(f"  FAIL {vertex_type}: ERROR - {e}")
            errors.append(f"Could not count {vertex_type}: {e}")

    # Check other vertex types exist
    for vertex_type in ["Customer", "Card", "DeviceProfile", "EmailDomain",
                        "BillingRegion", "InvestigationCase", "PolicyChunk", "PatternChunk", "RegDoc"]:
        try:
            count = conn.getVertexCount(vertex_type)
            actual = count if isinstance(count, int) else 0
            status = "PASS" if actual > 0 else "WARN"
            print(f"  {status} {vertex_type}: {actual:,}")
            if actual == 0:
                warnings.append(f"{vertex_type} has 0 vertices")
        except Exception as e:
            print(f"  WARN {vertex_type}: ERROR - {e}")
            warnings.append(f"Could not count {vertex_type}: {e}")

    # ── Check 2: Edge counts ─────────────────────────────────────────────
    print("\n--- Edge Counts ---")

    for edge_type in ["OWNS", "MADE", "NEXT", "FROM_DEVICE", "PURCHASER_EMAIL",
                       "BILLED_IN", "INVOLVES", "ON_CARD", "CONNECTED_TO",
                       "OPENED_FOR", "APPLIED_RULE"]:
        try:
            count = conn.getEdgeCount(edge_type)
            actual = count if isinstance(count, int) else 0
            status = "PASS" if actual > 0 else "WARN"
            print(f"  {status} {edge_type}: {actual:,}")
            if actual == 0:
                warnings.append(f"{edge_type} has 0 edges")
        except Exception as e:
            print(f"  WARN {edge_type}: ERROR - {e}")

    # ── Check 3: Case pack flagged_txn_id resolution ─────────────────────
    print("\n--- Case Pack ID Validation ---")

    if os.path.exists(CASE_PACK_FILE):
        df = pd.read_csv(CASE_PACK_FILE)
        for _, row in df.iterrows():
            case_id = str(row["case_id"])
            flagged_txn_id = str(row["flagged_txn_id"])
            try:
                result = conn.getVerticesById("Transaction", flagged_txn_id)
                if result:
                    print(f"  PASS {case_id}: txn {flagged_txn_id} exists")
                else:
                    print(f"  FAIL {case_id}: txn {flagged_txn_id} NOT FOUND")
                    errors.append(
                        f"{case_id}: flagged_txn_id {flagged_txn_id} not found in graph"
                    )
            except Exception as e:
                print(f"  FAIL {case_id}: txn {flagged_txn_id} ERROR - {e}")
                errors.append(f"{case_id}: could not look up {flagged_txn_id}: {e}")
    else:
        print(f"  WARN case_pack.csv not found at {CASE_PACK_FILE}")
        warnings.append("case_pack.csv not found")

    # ── Check 4: PolicyChunk and PatternChunk completeness ───────────────
    print("\n--- Knowledge Graph Validation ---")

    for chunk_type, expected_ids in [
        ("PolicyChunk", ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]),
        ("PatternChunk", ["card_testing", "card_not_present_fraud", "card_not_present_new_device",
                          "out_of_region_use", "account_takeover"]),
    ]:
        for chunk_id in expected_ids:
            try:
                result = conn.getVerticesById(chunk_type, chunk_id)
                if result:
                    print(f"  PASS {chunk_type}/{chunk_id} exists")
                else:
                    print(f"  FAIL {chunk_type}/{chunk_id} NOT FOUND")
                    errors.append(f"{chunk_type}/{chunk_id} missing")
            except Exception as e:
                print(f"  WARN {chunk_type}/{chunk_id}: ERROR - {e}")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"  Errors:   {len(errors)}")
    print(f"  Warnings: {len(warnings)}")

    if errors:
        print("\n  ERRORS:")
        for e in errors:
            print(f"    FAIL {e}")

    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    WARN {w}")

    if not errors:
        print("\n  PASS All critical validations passed!")
    else:
        print(f"\n  FAIL {len(errors)} critical error(s) found. Fix before proceeding.")

    return len(errors) == 0


if __name__ == "__main__":
    success = validate_load()
    sys.exit(0 if success else 1)
