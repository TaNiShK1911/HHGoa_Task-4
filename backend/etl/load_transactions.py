"""
ETL: Load transactions.csv into TigerGraph — Section 4, Step 2.

Streams transactions.csv in 50,000-row chunks (file is ~708 MB).
Uses bulk upsertVertices and upsertEdges via python dictionaries (skips buggy pyTigerGraph DataFrames).
"""

from __future__ import annotations

import os
import sys
import math
import logging
from typing import Any, Dict

import pandas as pd
import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHUNK_SIZE = 2500
DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "HHGOA_IEEE-20260919T091224Z-1-001", "HHGOA_IEEE"),
)
TRANSACTIONS_FILE = os.path.join(DATA_DIR, "transactions.csv")


def get_connection() -> tg.TigerGraphConnection:
    conn = tg.TigerGraphConnection(
        host=os.environ["TIGERGRAPH_HOST"],
        username=os.environ.get("TIGERGRAPH_USERNAME", "tigergraph"),
        password=os.environ["TIGERGRAPH_PASSWORD"],
        graphname=os.environ.get("TIGERGRAPH_GRAPH_NAME", "FraudInvestigation"),
    )
    
    token = os.environ.get("TIGERGRAPH_TOKEN")
    if token:
        conn.apiToken = token
    else:
        # Fallback to Secret if TOKEN isn't provided
        try:
            secret = os.environ.get("TIGERGRAPH_SECRET")
            if secret:
                conn.getToken(secret)
            else:
                conn.getToken(conn.createSecret())
        except Exception:
            logger.warning("Could not create secret/token. Proceeding without token auth.")
    return conn


def safe_str(val: Any) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val)


def safe_float(val: Any) -> float:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def load_transactions():
    if not os.path.exists(TRANSACTIONS_FILE):
        logger.error(f"File not found: {TRANSACTIONS_FILE}")
        sys.exit(1)

    conn = get_connection()
    logger.info(f"Connected to TigerGraph at {os.environ['TIGERGRAPH_HOST']}")
    
    total_txns = 155000

    for chunk_num, chunk in enumerate(pd.read_csv(TRANSACTIONS_FILE, chunksize=CHUNK_SIZE, low_memory=False, skiprows=range(1, 155000))):
        logger.info(f"Processing chunk {chunk_num + 1} ({len(chunk)} rows)...")

        customers = {}
        cards = {}
        regions = {}
        emails = {}
        txns = {}

        owns_edges = {}
        made_edges = {}
        billed_in_edges = {}
        purchaser_email_edges = {}

        for _, row in chunk.iterrows():
            txn_id = safe_str(row["TransactionID"])
            customer_id = safe_str(row["customer_id"])
            
            card1 = safe_float(row["card1"])
            card2 = safe_float(row.get("card2", 0))
            card3 = safe_float(row.get("card3", 0))
            card4 = safe_str(row.get("card4", ""))
            card5 = safe_float(row.get("card5", 0))
            card6 = safe_str(row.get("card6", ""))
            
            card_id = ""
            if customer_id:
                card_id = f"{customer_id}-K{int(card5) if card5 > 0 else 1}"

            region_code = safe_str(row.get("addr1", ""))
            country_code = safe_str(row.get("addr2", ""))
            
            p_email = safe_str(row.get("P_emaildomain", ""))
            r_email = safe_str(row.get("R_emaildomain", ""))
            
            ts = safe_str(row["ts"])

            if customer_id:
                customers[customer_id] = {"first_seen_ts": ts, "n_cards": 1}
            
            if card_id:
                cards[card_id] = {
                    "customer_id": customer_id, 
                    "card_network": card4, 
                    "card_type": card6, 
                    "card2": card2, 
                    "card3": card3, 
                    "card5": card5
                }
                
            if region_code:
                regions[region_code] = {"country_code": country_code}
                
            if p_email:
                emails[p_email] = {}
            if r_email:
                emails[r_email] = {}

            txn_attrs = {
                "customer_id": customer_id,
                "ts": ts,
                "channel": safe_str(row["channel"]),
                "risk_score": safe_float(row["risk_score"]),
                "TransactionDT": safe_float(row["TransactionDT"]),
                "TransactionAmt": safe_float(row["TransactionAmt"]),
                "ProductCD": safe_str(row["ProductCD"]),
                "card1": card1,
                "card2": card2,
                "card3": card3,
                "card4": card4,
                "card5": card5,
                "card6": card6,
                "addr1": safe_float(row.get("addr1", 0)),
                "addr2": safe_float(row.get("addr2", 0)),
                "dist1": safe_float(row.get("dist1", 0)),
                "dist2": safe_float(row.get("dist2", 0)),
                "P_emaildomain": p_email,
                "R_emaildomain": r_email,
            }
            
            for i in range(1, 15): txn_attrs[f"C{i}"] = safe_float(row.get(f"C{i}", 0))
            for i in range(1, 16): txn_attrs[f"D{i}"] = safe_float(row.get(f"D{i}", 0))
            for i in range(1, 10): txn_attrs[f"M{i}"] = safe_str(row.get(f"M{i}", ""))
            for i in range(1, 340): txn_attrs[f"V{i}"] = safe_float(row.get(f"V{i}", 0))
            txns[txn_id] = txn_attrs

            # Edges: Dict format is source_id: {target_id: {attributes}}
            if customer_id and card_id:
                if customer_id not in owns_edges: owns_edges[customer_id] = {}
                owns_edges[customer_id][card_id] = {}
                
            if card_id and txn_id:
                if card_id not in made_edges: made_edges[card_id] = {}
                made_edges[card_id][txn_id] = {}
                
            if region_code and txn_id:
                if txn_id not in billed_in_edges: billed_in_edges[txn_id] = {}
                billed_in_edges[txn_id][region_code] = {}
                
            if p_email and txn_id:
                if txn_id not in purchaser_email_edges: purchaser_email_edges[txn_id] = {}
                purchaser_email_edges[txn_id][p_email] = {}

        # Bulk upsert vertices
        try:
            if customers: conn.upsertVertices("Customer", list(customers.items()))
            if cards: conn.upsertVertices("Card", list(cards.items()))
            if regions: conn.upsertVertices("BillingRegion", list(regions.items()))
            if emails: conn.upsertVertices("EmailDomain", list(emails.items()))
            if txns: conn.upsertVertices("Transaction", list(txns.items()))
        except Exception as e:
            logger.error(f"Error bulk upserting vertices in chunk {chunk_num + 1}: {e}")

        # Bulk upsert edges
        try:
            if owns_edges: conn.upsertEdges("Customer", "OWNS", "Card", owns_edges)
            if made_edges: conn.upsertEdges("Card", "MADE", "Transaction", made_edges)
            if billed_in_edges: conn.upsertEdges("Transaction", "BILLED_IN", "BillingRegion", billed_in_edges)
            if purchaser_email_edges: conn.upsertEdges("Transaction", "PURCHASER_EMAIL", "EmailDomain", purchaser_email_edges)
        except Exception as e:
            logger.error(f"Error bulk upserting edges in chunk {chunk_num + 1}: {e}")

        total_txns += len(chunk)
        logger.info(f"  Total transactions processed so far: {total_txns}")

    logger.info(f"Transaction load complete. Total: {total_txns}")


if __name__ == "__main__":
    load_transactions()
