"""
ETL: Load case_pack.csv — Section 4, Step 7.

Loads the 20 exam cases into TigerGraph as trigger records.
Also mirrors them into a Supabase case_pack table so the frontend
can list all 20 without a TigerGraph round-trip.
"""

from __future__ import annotations

import os
import sys
import math
import json
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
CASE_PACK_FILE = os.path.join(DATA_DIR, "case_pack.csv")


def get_tg_connection() -> tg.TigerGraphConnection:
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


def get_supabase_client():
    """Create Supabase client from environment variables."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.warning("Supabase credentials not set. Skipping Supabase mirror.")
        return None
    from supabase import create_client
    return create_client(url, key)


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


def load_case_pack():
    """Load case_pack.csv into TigerGraph and Supabase."""
    if not os.path.exists(CASE_PACK_FILE):
        logger.error(f"File not found: {CASE_PACK_FILE}")
        sys.exit(1)

    conn = get_tg_connection()
    sb = get_supabase_client()

    # Read the 20-row case pack
    df = pd.read_csv(CASE_PACK_FILE)
    logger.info(f"Case pack loaded: {len(df)} cases")

    # Expected headers:
    # case_id, opened_at, trigger_type, trigger_text, flagged_txn_id, card_id, customer_id, risk_score

    for _, row in df.iterrows():
        case_id = safe_str(row["case_id"])
        logger.info(f"  Loading case: {case_id}")

        # Create Case vertex in TigerGraph (initial state)
        try:
            conn.upsertVertex("InvestigationCase", case_id, attributes={
                "status": "open",
                "verdict": "uncertain",
                "fraud_probability": safe_float(row.get("risk_score", 0)),
                "pattern": "none",
                "pattern_description": "",
                "exposure_usd": 0.0,
                "summary": "",
                "created_at": safe_str(row.get("opened_at", "")),
                "updated_at": safe_str(row.get("opened_at", "")),
            })
        except Exception as e:
            logger.error(f"    Case vertex error: {e}")

        # OPENED_FOR edge: Case -> flagged Transaction
        flagged_txn_id = safe_str(row.get("flagged_txn_id", ""))
        if flagged_txn_id:
            try:
                conn.upsertEdge("InvestigationCase", case_id, "OPENED_FOR", "Transaction", flagged_txn_id)
            except Exception as e:
                logger.debug(f"    OPENED_FOR edge error: {e}")

        # Mirror to Supabase
        if sb:
            try:
                sb.table("case_pack").upsert({
                    "case_id": case_id,
                    "opened_at": safe_str(row.get("opened_at", "")),
                    "trigger_type": safe_str(row.get("trigger_type", "")),
                    "trigger_text": safe_str(row.get("trigger_text", "")),
                    "flagged_txn_id": flagged_txn_id,
                    "card_id": safe_str(row.get("card_id", "")),
                    "customer_id": safe_str(row.get("customer_id", "")),
                    "risk_score": safe_float(row.get("risk_score", 0)),
                }).execute()
            except Exception as e:
                logger.error(f"    Supabase mirror error: {e}")

    logger.info(f"Case pack load complete: {len(df)} cases loaded.")


if __name__ == "__main__":
    load_case_pack()
