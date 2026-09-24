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
import re
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
    cases_dir = os.path.join(os.path.dirname(__file__), "..", "..", "cases")
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
    filepath = os.path.join(os.path.dirname(__file__), "..", "..", "cases", f"{case_id}.json")
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)

    raise HTTPException(status_code=404, detail=f"Case {case_id} not found")


# ── GET /api/cases/{case_id}/trace ───────────────────────────────────────────

@router.get("/cases/{case_id}/trace")
async def get_case_trace(case_id: str):
    """Ordered LangGraph node execution trace for the Investigation Trace UI.

    Returns a list of dicts matching the frontend TraceStep type:
      { node_name, timestamp, input_summary, output_summary, policy_rule_fired? }
    """
    # Try loading from Supabase audit_log
    sb = get_supabase()
    if sb:
        try:
            result = sb.table("audit_log").select("*").eq(
                "case_id", case_id
            ).order("created_at").execute()

            if result.data:
                # Map audit_log columns to the frontend TraceStep shape
                trace = []
                for row in result.data:
                    details = row.get("details") or {}
                    if isinstance(details, str):
                        import json as _json
                        try:
                            details = _json.loads(details)
                        except Exception:
                            details = {}
                    trace.append({
                        "node_name": row.get("node", "UNKNOWN"),
                        "timestamp": row.get("created_at", ""),
                        "input_summary": details.get("input_summary", ""),
                        "output_summary": details.get("output_summary", ""),
                        "policy_rule_fired": details.get("policy_rule_fired"),
                    })
                return trace
        except Exception as e:
            logger.warning(f"Audit log query failed: {e}")

    # Fallback: read from case file and reconstruct trace
    filepath = os.path.join(os.path.dirname(__file__), "..", "..", "cases", f"{case_id}.json")
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            data = json.load(f)

        return _reconstruct_trace(data)

    raise HTTPException(status_code=404, detail=f"Trace for case {case_id} not found")


# ── GET /api/cases/{case_id}/neighborhood ────────────────────────────────────

@router.get("/cases/{case_id}/neighborhood")
async def get_case_neighborhood(case_id: str):
    """
    Graph nodes/edges for the Graph View UI.
    Builds a subgraph from the answer file: case node at centre, connected
    cards, transactions, devices, customer, billing region, and prior cases.
    Extracts additional entities from evidence when the explicit arrays are
    empty (which is common for cases with limited graph hits).
    """
    # Get the case details first
    filepath = os.path.join(os.path.dirname(__file__), "..", "..", "cases", f"{case_id}.json")
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

    # Use sets to avoid duplicate node IDs
    seen_node_ids: set = set()
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    def _add_node(nid: str, ntype: str, label: str, **extra: Any) -> None:
        if nid in seen_node_ids:
            return
        seen_node_ids.add(nid)
        node: Dict[str, Any] = {"id": nid, "type": ntype, "label": label}
        node.update(extra)
        nodes.append(node)

    def _add_edge(source: str, target: str, label: str) -> None:
        edges.append({"source": source, "target": target, "label": label})

    # ── Central case node ────────────────────────────────────────────────
    _add_node(
        case_id, "InvestigationCase", case_id,
        verdict=case_detail.get("verdict", ""),
        pattern=case_detail.get("pattern", ""),
        fraud_probability=case_detail.get("fraud_probability", 0),
    )

    # ── Explicit arrays from the answer file ─────────────────────────────

    # Cards
    for cid in case_detail.get("connected_card_ids", []):
        _add_node(cid, "Card", cid)
        _add_edge(case_id, cid, "LINKS_CARD")

    # Affected transactions
    for txn_id in case_detail.get("affected_txn_ids", []):
        tid = str(txn_id)
        _add_node(tid, "Transaction", f"Txn {tid}")
        _add_edge(case_id, tid, "AFFECTS")

    # Similar prior cases
    for prior_id in case_detail.get("similar_prior_cases", []):
        _add_node(prior_id, "ClosedCase", prior_id)
        _add_edge(case_id, prior_id, "CITES")

    # Device profiles (now with edges!)
    for device in case_detail.get("connected_device_profiles", []):
        device_id = device[:30]
        _add_node(device_id, "DeviceProfile", device_id)
        _add_edge(case_id, device_id, "USED_DEVICE")

    # ── Extract additional entities from evidence ────────────────────────
    # When the explicit arrays are empty, the evidence still references
    # customers, cards, regions, and prior cases in its entity_ids / ref.

    for ev in case_detail.get("evidence", []):
        ref: str = ev.get("ref", "")
        entity_ids: List[str] = ev.get("entity_ids", [])

        # Customer IDs (e.g. "C08623")
        for eid in entity_ids:
            if eid.startswith("C") and eid[1:].isdigit():
                _add_node(eid, "Customer", f"Customer {eid}")
                _add_edge(case_id, eid, "BELONGS_TO")

        # Card IDs from evidence (e.g. "C08623-K2")
        for eid in entity_ids:
            if "-" in eid and not eid.startswith("CC-"):
                _add_node(eid, "Card", eid)
                _add_edge(case_id, eid, "LINKS_CARD")
                # Link card to customer if customer exists
                parts = eid.split("-")
                cust_id = parts[0]
                if cust_id in seen_node_ids:
                    _add_edge(cust_id, eid, "OWNS_CARD")

        # Closed cases from evidence (e.g. "CC-3931")
        for eid in entity_ids:
            if eid.startswith("CC-"):
                _add_node(eid, "ClosedCase", eid)
                _add_edge(case_id, eid, "CITES")

        # Policy rules from evidence (e.g. "R2", "R4")
        if ev.get("source") == "document":
            for eid in entity_ids:
                if eid.startswith("R") and eid[1:].isdigit():
                    _add_node(eid, "PolicyRule", f"Rule {eid}")
                    _add_edge(case_id, eid, "FIRES_RULE")

        # Billing region from evidence ref (e.g. "region_cluster(region_code=330, ...)")
        if "region_cluster" in ref:
            m = re.search(r"region_code=(\d+)", ref)
            if m:
                region_id = f"Region-{m.group(1)}"
                _add_node(region_id, "BillingRegion", region_id)
                _add_edge(case_id, region_id, "IN_REGION")

    # ── Link transactions to cards where possible ────────────────────────
    # If there is exactly one card and transactions, link them together.
    card_nodes = [n for n in nodes if n["type"] == "Card"]
    txn_nodes = [n for n in nodes if n["type"] == "Transaction"]
    if len(card_nodes) == 1 and txn_nodes:
        for txn in txn_nodes:
            _add_edge(card_nodes[0]["id"], txn["id"], "HAS_TXN")

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
        filepath = os.path.join(os.path.dirname(__file__), "..", "..", "cases", f"{case_id}.json")
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return json.load(f)
        return result.get("_answer_file", {"status": "completed", "case_id": case_id})
    except Exception as e:
        logger.error(f"Agent run failed for {case_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Agent run failed: {str(e)}")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _reconstruct_trace(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reconstruct an investigation trace from the answer file data.

    Returns dicts matching the frontend TraceStep type:
      { node_name, timestamp, input_summary, output_summary, policy_rule_fired? }
    """
    trace: List[Dict[str, Any]] = []
    step = 1

    def _summarise(d: Any) -> str:
        """Convert a dict/value to a short human-readable string."""
        if isinstance(d, dict):
            parts = []
            for k, v in d.items():
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v) if v else "none"
                parts.append(f"{k}: {v}")
            return "; ".join(parts)
        return str(d) if d else "—"

    # Trigger
    trace.append({
        "node_name": "TRIGGER",
        "timestamp": data.get("case", {}).get("opened_at", ""),
        "input_summary": f"Case {data.get('case_id', '')} loaded from case pack",
        "output_summary": f"Trigger loaded for case {data.get('case_id', '')}",
    })
    step += 1

    # Evidence gathering
    evidence = data.get("case", {}).get("evidence", [])
    for ev in evidence:
        source = ev.get("source", "unknown")
        trace.append({
            "node_name": "GATHER_EVIDENCE",
            "timestamp": "",
            "input_summary": f"Source: {source} — {ev.get('ref', '')}",
            "output_summary": ev.get("claim", ""),
        })
        step += 1

    # Memory retrieval
    prior_cases = data.get("case", {}).get("similar_prior_cases", [])
    trace.append({
        "node_name": "RETRIEVE_MEMORY",
        "timestamp": "",
        "input_summary": "Vector search for similar closed cases",
        "output_summary": f"Found {len(prior_cases)} similar prior case(s)" + (
            f": {', '.join(prior_cases)}" if prior_cases else ""
        ),
    })
    step += 1

    # Assessment
    case_detail = data.get("case", {})
    pattern = case_detail.get("pattern", "none")
    prob = case_detail.get("fraud_probability", 0)
    verdict = case_detail.get("verdict", "")
    trace.append({
        "node_name": "ASSESS",
        "timestamp": "",
        "input_summary": "Synthesise evidence into verdict, pattern, and probability",
        "output_summary": f"Verdict: {verdict} | Probability: {prob} | Pattern: {pattern}",
        "policy_rule_fired": pattern if pattern and pattern != "none" else None,
    })
    step += 1

    # Initial actions
    initial_actions = data.get("next_best_actions", {}).get("initial", [])
    trace.append({
        "node_name": "DECIDE_ACTIONS_INITIAL",
        "timestamp": "",
        "input_summary": "Determine initial recommended actions before evidence request",
        "output_summary": ", ".join(
            a.get("action", "") for a in initial_actions
        ) or "No initial actions",
    })
    step += 1

    # Evidence requests
    for er in data.get("evidence_requests", []):
        trace.append({
            "node_name": "REQUEST_EVIDENCE",
            "timestamp": "",
            "input_summary": f"Type: {er.get('type', '')} — asked after step {er.get('asked_after_step', '?')}",
            "output_summary": er.get("assumed_response", "—"),
        })
        step += 1

    # Final actions
    final_actions = data.get("next_best_actions", {}).get("final", [])
    what_changed = data.get("next_best_actions", {}).get("what_changed", "")
    trace.append({
        "node_name": "DECIDE_ACTIONS_FINAL",
        "timestamp": "",
        "input_summary": "Re-evaluate actions after evidence response",
        "output_summary": ", ".join(
            a.get("action", "") for a in final_actions
        ) + (f" — {what_changed}" if what_changed else ""),
    })
    step += 1

    # SAR decision
    sar = data.get("sar", {})
    trace.append({
        "node_name": "SAR_DECISION",
        "timestamp": "",
        "input_summary": "Evaluate whether a Suspicious Activity Report should be filed",
        "output_summary": ("SAR to be filed" if sar.get("file") else "No SAR required") + (
            f" — {sar.get('reason', '')}" if sar.get("reason") else ""
        ),
    })
    step += 1

    # Stop
    trace.append({
        "node_name": "STOP",
        "timestamp": "",
        "input_summary": "Investigation concluded",
        "output_summary": data.get("stop_reason", "—"),
    })

    return trace
