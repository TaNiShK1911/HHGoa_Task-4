"""
Batch execution script — Section 9 of the implementation plan.

Runs the LangGraph agent across all 20 cases in the case pack.
Automatically saves answer files to cases/ and mirrors to Supabase.
Requires TigerGraph, Groq, and Supabase credentials to be set.
"""

from __future__ import annotations

import os
import sys
import logging
import math
import time

import pandas as pd
from dotenv import load_dotenv

# Ensure the backend directory is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.graph import build_investigation_graph
from agent.groq_client import GroqClient
from agent.tools_mcp import TigerGraphTools

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "HHGOA_IEEE-20260919T091224Z-1-001", "HHGOA_IEEE"),
)
CASE_PACK_FILE = os.path.join(DATA_DIR, "case_pack.csv")


def get_supabase_client():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def run_batch():
    if not os.path.exists(CASE_PACK_FILE):
        logger.error(f"Case pack not found: {CASE_PACK_FILE}")
        sys.exit(1)

    if not os.environ.get("GROQ_API_KEY"):
        logger.error("GROQ_API_KEY not set. Cannot run agent.")
        sys.exit(1)

    tg_tools = TigerGraphTools()
    try:
        # Check TigerGraph connection
        tg_tools._get_conn()
    except Exception as e:
        logger.error(f"TigerGraph connection failed: {e}")
        sys.exit(1)

    sb_client = get_supabase_client()
    if not sb_client:
        logger.warning("Supabase credentials missing. Will not write to Supabase.")

    groq_client = GroqClient()
    graph = build_investigation_graph(tg_tools, groq_client, sb_client)

    df = pd.read_csv(CASE_PACK_FILE)
    logger.info(f"Loaded {len(df)} cases from {CASE_PACK_FILE}")

    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "cases"), exist_ok=True)

    success_count = 0
    start_time = time.time()

    for idx, row in df.iterrows():
        case_id = str(row["case_id"])
        flagged_txn_id = str(row["flagged_txn_id"])
        card_id = str(row["card_id"])
        customer_id = str(row["customer_id"])
        trigger_type = str(row["trigger_type"])
        trigger_text = str(row["trigger_text"])
        
        rs = row.get("risk_score", 0)
        risk_score = float(rs) if not (isinstance(rs, float) and math.isnan(rs)) else 0.0
        
        opened_at = str(row.get("opened_at", ""))

        logger.info("-" * 50)
        logger.info(f"[{idx+1}/{len(df)}] Processing {case_id}")
        logger.info("-" * 50)

        groq_client.reset_token_count()
        tg_tools.reset_tool_call_count()

        initial_state = {
            "case_id": case_id,
            "flagged_txn_id": flagged_txn_id,
            "card_id": card_id,
            "customer_id": customer_id,
            "trigger_type": trigger_type,
            "trigger_text": trigger_text,
            "risk_score": risk_score,
            "opened_at": opened_at,
        }

        try:
            result = graph.invoke(initial_state)
            ans = result.get("_answer_file", {})
            v = ans.get("case", {}).get("verdict", "unknown")
            p = ans.get("case", {}).get("pattern", "unknown")
            e = ans.get("case", {}).get("exposure_usd", 0.0)
            
            logger.info(f"✓ {case_id} complete | verdict={v} | pattern={p} | exposure=${e:.2f}")
            logger.info(f"  Tool calls: {result.get('tool_calls', 0)}")
            logger.info(f"  Tokens: {result.get('tokens', 0)}")
            logger.info(f"  Latency: {result.get('latency_s', 0.0)}s")
            
            success_count += 1
        except Exception as e:
            logger.error(f"✗ {case_id} FAILED: {e}")

    elapsed = time.time() - start_time
    logger.info("=" * 50)
    logger.info("BATCH EXECUTION COMPLETE")
    logger.info(f"Successfully processed: {success_count}/{len(df)}")
    logger.info(f"Total time elapsed: {elapsed:.1f}s")
    logger.info(f"Average time per case: {elapsed/max(1, len(df)):.1f}s")
    logger.info("=" * 50)
    
    logger.info("Next step: Run `python scripts/validate_all_cases.py` to verify output.")


if __name__ == "__main__":
    run_batch()
