"""
ETL: Load closed_cases_history.csv — Section 4, Step 5.

Reads closed_cases_history.csv (5,565 rows).
Explodes pipe-separated txn_ids and connected_card_ids columns.
Creates ClosedCase vertices + INVOLVES, ON_CARD, CONNECTED_TO edges.

Uses bulk dictionary upserts for speed.
"""

from __future__ import annotations

import os
import sys
import math
import logging

import pandas as pd
import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "HHGOA_IEEE-20260919T091224Z-1-001", "HHGOA_IEEE"),
)
CLOSED_CASES_FILE = os.path.join(DATA_DIR, "closed_cases_history.csv")


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


def safe_str(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val)


def safe_float(val) -> float:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def load_closed_cases():
    """Load closed cases and create vertices + edges using bulk upserts."""
    if not os.path.exists(CLOSED_CASES_FILE):
        logger.error(f"File not found: {CLOSED_CASES_FILE}")
        sys.exit(1)

    conn = get_connection()
    logger.info(f"Loading closed cases from: {CLOSED_CASES_FILE}")

    df = pd.read_csv(CLOSED_CASES_FILE)
    logger.info(f"Closed cases loaded: {len(df)}")

    # Build bulk dictionaries
    cases = {}
    on_card_edges = {}      # ClosedCase -> Card
    involves_edges = {}     # ClosedCase -> Transaction
    connected_to_edges = {} # ClosedCase -> Card

    for _, row in df.iterrows():
        case_id = safe_str(row["case_id"])
        customer_id = safe_str(row["customer_id"])
        card_id = safe_str(row["card_id"])

        if not case_id:
            continue

        # ClosedCase vertex
        cases[case_id] = {
            "customer_id": customer_id,
            "card_id": card_id,
            "opened_at": safe_str(row.get("opened_at", "")),
            "closed_at": safe_str(row.get("closed_at", "")),
            "outcome": safe_str(row.get("outcome", "")),
            "pattern": safe_str(row.get("pattern", "")),
            "first_fraud_txn_id": safe_str(row.get("first_fraud_txn_id", "")),
            "n_txns": int(safe_float(row.get("n_txns", 0))),
            "exposure_usd": safe_float(row.get("exposure_usd", 0)),
            "actions_taken": safe_str(row.get("actions_taken", "")),
            "report_filed": safe_str(row.get("report_filed", "")),
            "analyst_notes": safe_str(row.get("analyst_notes", "")),
        }

        # ON_CARD edge: ClosedCase -> Card (primary card)
        if card_id:
            if case_id not in on_card_edges:
                on_card_edges[case_id] = {}
            on_card_edges[case_id][card_id] = {}

        # INVOLVES edges: ClosedCase -> Transaction (explode pipe-separated)
        txn_ids_str = safe_str(row.get("txn_ids", ""))
        if txn_ids_str:
            if case_id not in involves_edges:
                involves_edges[case_id] = {}
            for txn_id in txn_ids_str.split("|"):
                txn_id = txn_id.strip()
                if txn_id:
                    involves_edges[case_id][txn_id] = {}

        # CONNECTED_TO edges: ClosedCase -> Card (explode pipe-separated)
        connected_str = safe_str(row.get("connected_card_ids", ""))
        if connected_str:
            if case_id not in connected_to_edges:
                connected_to_edges[case_id] = {}
            for ccard in connected_str.split("|"):
                ccard = ccard.strip()
                if ccard:
                    connected_to_edges[case_id][ccard] = {}

    # Bulk upsert vertices
    logger.info(f"Upserting {len(cases)} ClosedCase vertices...")
    if cases:
        conn.upsertVertices("ClosedCase", list(cases.items()))

    # Bulk upsert edges
    logger.info(f"Upserting ON_CARD edges ({len(on_card_edges)} sources)...")
    if on_card_edges:
        conn.upsertEdges("ClosedCase", "ON_CARD", "Card", on_card_edges)

    logger.info(f"Upserting INVOLVES edges ({len(involves_edges)} sources)...")
    if involves_edges:
        conn.upsertEdges("ClosedCase", "INVOLVES", "Transaction", involves_edges)

    logger.info(f"Upserting CONNECTED_TO edges ({len(connected_to_edges)} sources)...")
    if connected_to_edges:
        conn.upsertEdges("ClosedCase", "CONNECTED_TO", "Card", connected_to_edges)

    logger.info("Closed cases load complete.")


if __name__ == "__main__":
    load_closed_cases()
