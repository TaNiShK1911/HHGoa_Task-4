"""
API Routes — Section 10 of the implementation plan.

Endpoints:
  GET  /api/cases                          -> list of case summaries
  GET  /api/cases/{case_id}                -> full AnswerFile JSON
  GET  /api/cases/{case_id}/trace          -> ordered LangGraph node execution trace
  GET  /api/cases/{case_id}/neighborhood   -> { nodes, edges } graph subgraph
  POST /api/cases/{case_id}/run            -> re-run agent for one case
  GET  /api/health                         -> { "status": "ok" }
"""

from __future__ import annotations

import json
import os
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def get_supabase():
    """Get Supabase client (lazy import to avoid circular deps)."""
    from main import get_supabase_client
    return get_supabase_client()


def get_tg_tools():
    """Get TigerGraph tools (lazy import)."""
    from main import get_tg_tools
    return get_tg_tools()


def get_groq():
    """Get Groq client (lazy import)."""
    from main import get_groq_client
    return get_groq_client()


# ── GET /api/health ──────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    """Health check endpoint for Render."""
    return {"status": "ok"}


# ── GET /api/cases ───────────────────────────────────────────────────────────

@router.get("/cases")
async def list_cases():
    """List all 20 case summaries from Supabase."""
    sb = get_supabase()

    if sb:
        try:
            result = sb.table("cases").select(
                "case_id, status, verdict, fraud_probability, pattern, "
                "exposure_usd, summary, updated_at"
            ).order("case_id").execute()

            if result.data:
                return {"cases": result.data, "total": len(result.data)}
        except Exception as e:
            logger.warning(f"Supabase query failed: {e}")

    # Fallback: read from local case files
    cases_dir = os.path.join(os.path.dirname(__file__), "..", "cases")
    cases = []

    if os.path.exists(cases_dir):
        for filename in sorted(os.listdir(cases_dir)):
            if filename.endswith(".json"):
                filepath = os.path.join(cases_dir, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                    case_detail = data.get("case", {})
                    cases.append({
                        "case_id": data.get("case_id", ""),
                        "status": case_detail.get("status", ""),
                        "verdict": case_detail.get("verdict", ""),
                        "fraud_probability": case_detail.get("fraud_probability", 0),
                        "pattern": case_detail.get("pattern", ""),
                        "exposure_usd": case_detail.get("exposure_usd", 0),
                        "summary": case_detail.get("summary", "")[:200],
                    })
                except Exception as e:
                    logger.error(f"Error reading {filename}: {e}")

    return {"cases": cases, "total": len(cases)}


# ── GET /api/cases/{case_id} ─────────────────────────────────────────────────

@router.get("/cases/{case_id}")
async def get_case(case_id: str):
    """Full AnswerFile JSON for one case."""
    # Try Supabase first
    sb = get_supabase()
    if sb:
        try:
            result = sb.table("cases").select("payload").eq("case_id", case_id).execute()
            if result.data and result.data[0].get("payload"):
                payload = result.data[0]["payload"]
                if isinstance(payload, str):
                    return json.loads(payload)
                return payload
        except Exception as e:
            logger.warning(f"Supabase query failed: {e}")

    # Fallback: read from local file
    filepath = os.path.join(os.path.dirname(__file__), "..", "cases", f"{case_id}.json")
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)

    raise HTTPException(status_code=404, detail=f"Case {case_id} not found")


# ── GET /api/cases/{case_id}/trace ───────────────────────────────────────────

@router.get("/cases/{case_id}/trace")
async def get_case_trace(case_id: str):
    """Ordered LangGraph node execution trace for the Investigation Trace UI."""
    # Try loading from Supabase audit_log
    sb = get_supabase()
    if sb:
        try:
            result = sb.table("audit_log").select("*").eq(
                "case_id", case_id
            ).order("created_at").execute()

            if result.data:
                return {
                    "case_id": case_id,
                    "trace": result.data,
                    "total_steps": len(result.data),
                }
        except Exception as e:
            logger.warning(f"Audit log query failed: {e}")

    # Fallback: read from case file and reconstruct trace
    filepath = os.path.join(os.path.dirname(__file__), "..", "cases", f"{case_id}.json")
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            data = json.load(f)

        # Reconstruct a trace from the answer file
        trace = _reconstruct_trace(data)
        return {
            "case_id": case_id,
            "trace": trace,
            "total_steps": len(trace),
        }

    raise HTTPException(status_code=404, detail=f"Trace for case {case_id} not found")


# ── GET /api/cases/{case_id}/neighborhood ────────────────────────────────────

@router.get("/cases/{case_id}/neighborhood")
async def get_case_neighborhood(case_id: str):
    """
    Graph nodes/edges for the Graph View UI.
    Queries TigerGraph for the card/device/region subgraph around this case.
    """
    tg_tools = get_tg_tools()

    # Get the case details first
    filepath = os.path.join(os.path.dirname(__file__), "..", "cases", f"{case_id}.json")
    case_data = None

    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            case_data = json.load(f)

    if not case_data:
        sb = get_supabase()
        if sb:
            try:
                result = sb.table("cases").select("payload").eq("case_id", case_id).execute()
                if result.data:
                    payload = result.data[0].get("payload", "{}")
                    case_data = json.loads(payload) if isinstance(payload, str) else payload
            except Exception:
                pass

    if not case_data:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case_detail = case_data.get("case", {})

    # Build the neighborhood graph
    nodes = []
    edges = []

    # Add the case node
    nodes.append({
        "id": case_id,
        "type": "InvestigationCase",
        "label": case_id,
        "verdict": case_detail.get("verdict", ""),
        "pattern": case_detail.get("pattern", ""),
    })

    # Add card nodes and edges
    card_id = case_data.get("case", {}).get("graph_case_id", "")
    # Use connected_card_ids from case detail
    all_card_ids = case_detail.get("connected_card_ids", [])

    for cid in all_card_ids:
        nodes.append({"id": cid, "type": "Card", "label": cid})
        edges.append({"source": case_id, "target": cid, "type": "LINKS_CARD"})

    # Add affected transactions
    for txn_id in case_detail.get("affected_txn_ids", [])[:10]:
        nodes.append({"id": str(txn_id), "type": "Transaction", "label": f"Txn {txn_id}"})
        edges.append({"source": case_id, "target": str(txn_id), "type": "AFFECTS"})

    # Add similar prior cases
    for prior_id in case_detail.get("similar_prior_cases", []):
        nodes.append({"id": prior_id, "type": "ClosedCase", "label": prior_id})
        edges.append({"source": case_id, "target": prior_id, "type": "CITES"})

    # Add device profiles
    for device in case_detail.get("connected_device_profiles", []):
        device_id = device[:30]  # Truncate for display
        nodes.append({"id": device_id, "type": "DeviceProfile", "label": device_id})

    return {
        "case_id": case_id,
        "nodes": nodes,
        "edges": edges,
    }


# ── POST /api/cases/{case_id}/run ────────────────────────────────────────────

@router.post("/cases/{case_id}/run")
async def run_case(case_id: str):
    """
    Re-run the LangGraph agent for one case.
    Returns the updated AnswerFile.
    """
    import pandas as pd

    tg_tools = get_tg_tools()
    groq = get_groq()
    sb = get_supabase()

    # Load case pack data
    data_dir = os.environ.get(
        "DATA_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "HHGOA_IEEE-20260919T091224Z-1-001", "HHGOA_IEEE"),
    )
    case_pack_file = os.path.join(data_dir, "case_pack.csv")

    case_row = None
    if os.path.exists(case_pack_file):
        df = pd.read_csv(case_pack_file)
        matches = df[df["case_id"] == case_id]
        if not matches.empty:
            case_row = matches.iloc[0].to_dict()
    else:
        # Try Supabase
        if sb:
            try:
                result = sb.table("case_pack").select("*").eq("case_id", case_id).execute()
                if result.data:
                    case_row = result.data[0]
            except Exception:
                pass

    if not case_row:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found in case pack")

    # Build the investigation graph and run
    from agent.graph import build_investigation_graph

    groq.reset_token_count()
    tg_tools.reset_tool_call_count()

    graph = build_investigation_graph(tg_tools, groq, sb)

    import math

    initial_state = {
        "case_id": case_id,
        "flagged_txn_id": str(case_row.get("flagged_txn_id", "")),
        "card_id": str(case_row.get("card_id", "")),
        "customer_id": str(case_row.get("customer_id", "")),
        "trigger_type": str(case_row.get("trigger_type", "")),
        "trigger_text": str(case_row.get("trigger_text", "")),
        "risk_score": float(case_row.get("risk_score", 0)) if not (isinstance(case_row.get("risk_score"), float) and math.isnan(case_row.get("risk_score"))) else 0.0,
        "opened_at": str(case_row.get("opened_at", "")),
    }

    try:
        result = graph.invoke(initial_state)
        # Read the written answer file
        filepath = os.path.join(os.path.dirname(__file__), "..", "cases", f"{case_id}.json")
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return json.load(f)
        return result.get("_answer_file", {"status": "completed", "case_id": case_id})
    except Exception as e:
        logger.error(f"Agent run failed for {case_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Agent run failed: {str(e)}")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _reconstruct_trace(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reconstruct an investigation trace from the answer file data."""
    trace = []
    step = 1

    # Trigger
    trace.append({
        "step": step, "node": "TRIGGER",
        "output": {"case_id": data.get("case_id"), "trigger": "loaded from case pack"},
    })
    step += 1

    # Evidence gathering
    evidence = data.get("case", {}).get("evidence", [])
    for ev in evidence:
        if ev.get("source") == "graph":
            trace.append({
                "step": step, "node": "GATHER_EVIDENCE",
                "output": {"claim": ev.get("claim", ""), "ref": ev.get("ref", "")},
            })
            step += 1

    # Memory retrieval
    prior_cases = data.get("case", {}).get("similar_prior_cases", [])
    trace.append({
        "step": step, "node": "RETRIEVE_MEMORY",
        "output": {"similar_prior_cases": prior_cases},
    })
    step += 1

    # Assessment
    trace.append({
        "step": step, "node": "ASSESS",
        "output": {
            "pattern": data.get("case", {}).get("pattern"),
            "fraud_probability": data.get("case", {}).get("fraud_probability"),
            "verdict": data.get("case", {}).get("verdict"),
        },
    })
    step += 1

    # Initial actions
    trace.append({
        "step": step, "node": "DECIDE_ACTIONS_INITIAL",
        "output": {"actions": data.get("next_best_actions", {}).get("initial", [])},
    })
    step += 1

    # Evidence requests
    for er in data.get("evidence_requests", []):
        trace.append({
            "step": step, "node": "REQUEST_EVIDENCE",
            "output": er,
        })
        step += 1

    # Final actions
    trace.append({
        "step": step, "node": "DECIDE_ACTIONS_FINAL",
        "output": {
            "actions": data.get("next_best_actions", {}).get("final", []),
            "what_changed": data.get("next_best_actions", {}).get("what_changed"),
        },
    })
    step += 1

    # SAR decision
    trace.append({
        "step": step, "node": "SAR_DECISION",
        "output": {
            "file": data.get("sar", {}).get("file"),
            "reason": data.get("sar", {}).get("reason"),
        },
    })
    step += 1

    # Stop
    trace.append({
        "step": step, "node": "STOP",
        "output": {"stop_reason": data.get("stop_reason")},
    })

    return trace
