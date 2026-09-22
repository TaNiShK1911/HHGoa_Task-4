"""
ETL: Load identity.csv into TigerGraph — Section 4, Step 3.

Reads identity.csv fully (26 MB, fits in memory).
Uses dictionary-based bulk upserts to avoid pyTigerGraph dataframe bugs.
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
IDENTITY_FILE = os.path.join(DATA_DIR, "identity.csv")


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


def make_device_key(row: pd.Series) -> str:
    device_info = safe_str(row.get("DeviceInfo", ""))
    id_30 = safe_str(row.get("id_30", ""))
    id_31 = safe_str(row.get("id_31", ""))
    id_33 = safe_str(row.get("id_33", ""))
    return f"{device_info}|{id_30}|{id_31}|{id_33}"


def load_identity():
    if not os.path.exists(IDENTITY_FILE):
        logger.error(f"File not found: {IDENTITY_FILE}")
        sys.exit(1)

    conn = get_connection()
    logger.info(f"Connected to TigerGraph")

    df = pd.read_csv(IDENTITY_FILE, low_memory=False)
    logger.info(f"Identity records loaded: {len(df)}")

    devices = {}
    edges = {}

    for _, row in df.iterrows():
        txn_id = safe_str(row["TransactionID"])
        device_key = make_device_key(row)

        if not device_key or device_key == "|||":
            continue

        is_new = safe_str(row.get("id_15", "")) == "New"
        devices[device_key] = {
            "device_type": safe_str(row.get("DeviceType", "")),
            "device_info": safe_str(row.get("DeviceInfo", "")),
            "os": safe_str(row.get("id_30", "")),
            "browser": safe_str(row.get("id_31", "")),
            "screen": safe_str(row.get("id_33", "")),
            "is_new_flag_seen": is_new,
        }
        
        if txn_id not in edges:
            edges[txn_id] = {}
        edges[txn_id][device_key] = {}

    logger.info("Bulk upserting DeviceProfile vertices...")
    if devices:
        items = list(devices.items())
        for i in range(0, len(items), 5000):
            conn.upsertVertices("DeviceProfile", items[i:i+5000])

    logger.info("Bulk upserting FROM_DEVICE edges...")
    if edges:
        items = list(edges.items())
        for i in range(0, len(items), 5000):
            # For edges, items is a list of tuples (source_id, target_dict)
            batch = dict(items[i:i+5000])
            conn.upsertEdges("Transaction", "FROM_DEVICE", "DeviceProfile", batch)

    logger.info(f"Identity load complete. Unique devices: {len(devices)}")


if __name__ == "__main__":
    load_identity()
