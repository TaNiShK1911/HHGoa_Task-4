"""
LangGraph State Machine — Section 6 of the implementation plan.

Exact node sequence:
    TRIGGER → LOAD_CASE_CONTEXT → GATHER_EVIDENCE → RETRIEVE_MEMORY → ASSESS →
    SINGLE_SIGNAL_CHECK → DECIDE_ACTIONS_INITIAL → NEED_MORE_EVIDENCE? →
        [yes: REQUEST_EVIDENCE → RE_ASSESS → DECIDE_ACTIONS_FINAL]
        [no:  final = initial] →
    STOP_CHECK → SAR_DECISION → SAR_WRITE (conditional) →
    WRITE_CASE_TO_GRAPH → EMIT_ANSWER_FILE

State is a single typed dict matching the AnswerFile schema field-for-field.
Only ASSESS and SAR_WRITE nodes call Groq. All others are tool calls or
deterministic Python.
"""

from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from agent.groq_client import GroqClient
from agent.policy_engine import (
    Action,
    EvidenceBundle,
    decide_final,
    decide_initial,
    route_for_exposure,
    sar_decision,
)
from agent.tools_mcp import TigerGraphTools
from schema.answer_schema import AnswerFile

logger = logging.getLogger(__name__)


# ── Agent State ──────────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """
    The investigation state carried through every node.
    Maps field-for-field to the AnswerFile schema.
    """
    # Case identification
    case_id: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    trigger_type: str
    trigger_text: str
    risk_score: float
    opened_at: str

    # Case detail fields (Part 1)
    status: str
    verdict: str
    fraud_probability: float
    pattern: str
    pattern_description: str
    affected_txn_ids: List[str]
    first_suspicious_txn_id: str
    connected_card_ids: List[str]
    connected_device_profiles: List[str]
    exposure_usd: float
    evidence: List[Dict[str, Any]]
    similar_prior_cases: List[str]
    summary: str
    written_to_graph: bool
    graph_case_id: str

    # Evidence requests
    evidence_requests: List[Dict[str, Any]]

    # Next best actions (Part 3)
    initial_actions: List[Dict[str, Any]]
    final_actions: List[Dict[str, Any]]
    what_changed: str

    # SAR (Part 2)
    sar_file: bool
    sar_reason: str
    sar_narrative: str
    sar_subjects: List[str]
    sar_total_amount_usd: float
    sar_activity_dates: List[str]

    # Meta
    stop_reason: str
    tool_calls: int
    tokens: int
    latency_s: float
    start_time: float

    # Internal working state
    _evidence_bundle: Dict[str, Any]
    _case_context: Dict[str, Any]
    _similar_cases: List[Dict[str, Any]]
    _txn_details: List[Dict[str, Any]]
    _device_key: str
    _region_code: str
    _reg_doc_chunks: List[str]
    _current_step: int
    _needs_more_evidence: bool
    _customer_reply: Optional[str]
    _node_trace: List[Dict[str, Any]]


# ── Node implementations ────────────────────────────────────────────────────

def trigger_node(state: AgentState) -> AgentState:
    """TRIGGER: Initialize state from case pack row."""
    state["start_time"] = time.time()
    state["_current_step"] = 0
    state["_node_trace"] = []
    state["evidence"] = []
    state["evidence_requests"] = []
    state["affected_txn_ids"] = []
    state["connected_card_ids"] = []
    state["connected_device_profiles"] = []
    state["similar_prior_cases"] = []
    state["initial_actions"] = []
    state["final_actions"] = []
    state["_similar_cases"] = []
    state["_txn_details"] = []
    state["_reg_doc_chunks"] = []
    state["_needs_more_evidence"] = False
    state["_customer_reply"] = None
    state["tool_calls"] = 0
    state["tokens"] = 0
    state["status"] = "open"
    state["verdict"] = "uncertain"
    state["fraud_probability"] = state.get("risk_score", 0.5)
    state["pattern"] = "none"
    state["pattern_description"] = ""
    state["exposure_usd"] = 0.0
    state["written_to_graph"] = False
    state["graph_case_id"] = ""
    state["summary"] = ""
    state["sar_file"] = False
    state["sar_reason"] = ""
    state["sar_narrative"] = ""
    state["sar_subjects"] = []
    state["sar_total_amount_usd"] = 0.0
    state["sar_activity_dates"] = []
    state["stop_reason"] = ""
    state["what_changed"] = "nothing"

    # Fix 2: Customer report trigger = implicit denial.
    # "I never made this purchase" is a denial — apply R2 downstream.
    if state.get("trigger_type") == "customer_report":
        state["_customer_reply"] = "denied"
        trigger_text = state.get("trigger_text", "")
        state["evidence"].append({
            "claim": f"Customer filed a report denying the transaction: {trigger_text}",
            "source": "customer",
            "ref": "trigger:customer_report",
            "entity_ids": [state.get("customer_id", ""), state.get("card_id", "")],
        })
        state["evidence_requests"].append({
            "type": "customer_validation",
            "asked_after_step": 0,
            "assumed_response": trigger_text,
        })

    _log_node(state, "TRIGGER", {"case_id": state["case_id"]})
    return state


def load_case_context(state: AgentState, tg_tools: TigerGraphTools) -> AgentState:
    """LOAD_CASE_CONTEXT: Pull flagged transaction, card, customer from graph."""
    _log_node(state, "LOAD_CASE_CONTEXT", {"flagged_txn_id": state["flagged_txn_id"]})

    # Get the flagged transaction details
    try:
        conn = tg_tools._get_conn()
        txn = conn.getVerticesById("Transaction", state["flagged_txn_id"])
        if txn:
            attrs = txn[0].get("attributes", txn[0]) if isinstance(txn, list) else txn.get("attributes", txn)
            state["_case_context"] = {
                "case_id": state["case_id"],
                "flagged_txn_id": state["flagged_txn_id"],
                "card_id": state["card_id"],
                "customer_id": state["customer_id"],
                "trigger_type": state["trigger_type"],
                "trigger_text": state["trigger_text"],
                "risk_score": state.get("risk_score", 0),
                "amount": attrs.get("TransactionAmt", 0),
                "product_cd": attrs.get("ProductCD", ""),
                "channel": attrs.get("channel", ""),
                "ts": attrs.get("ts", ""),
                "addr1": attrs.get("addr1", ""),
                "addr2": attrs.get("addr2", ""),
                "P_emaildomain": attrs.get("P_emaildomain", ""),
            }
            state["_region_code"] = str(attrs.get("addr1", ""))
            tg_tools._tool_call_count += 1

            # Look up device profile for this transaction via FROM_DEVICE edge
            try:
                device_edges = conn.getEdges("Transaction", state["flagged_txn_id"], "FROM_DEVICE")
                if device_edges:
                    device_key = device_edges[0].get("to_id", "")
                    state["_device_key"] = device_key
                    if device_key:
                        state["connected_device_profiles"] = [device_key]
                    tg_tools._tool_call_count += 1
                else:
                    state["_device_key"] = ""
            except Exception as e:
                logger.warning(f"Could not look up device profile: {e}")
                state["_device_key"] = ""
        else:
            state["_case_context"] = {
                "case_id": state["case_id"],
                "flagged_txn_id": state["flagged_txn_id"],
                "card_id": state["card_id"],
                "customer_id": state["customer_id"],
            }
            state["_region_code"] = ""
            state["_device_key"] = ""
    except Exception as e:
        logger.error(f"Failed to load case context: {e}")
        state["_case_context"] = {
            "case_id": state["case_id"],
            "flagged_txn_id": state["flagged_txn_id"],
        }
        state["_region_code"] = ""
        state["_device_key"] = ""

    return state


def gather_evidence(state: AgentState, tg_tools: TigerGraphTools) -> AgentState:
    """GATHER_EVIDENCE: Parallel GSQL queries — card_window, device_neighbors, region_cluster, customer_baseline."""
    _log_node(state, "GATHER_EVIDENCE", {})

    # Tool 1: Card window — get recent transactions on this card
    card_evidence = tg_tools.card_window(state["card_id"], hours=48)
    state["evidence"].append(_to_evidence(card_evidence))
    state["_txn_details"] = card_evidence.get("_details", [])

    # Identify high-risk transactions in the window as potentially affected
    flagged = state.get("flagged_txn_id", "")
    for txn in card_evidence.get("_details", []):
        txn_id = txn.get("txn_id", "")
        rs = txn.get("risk_score", 0)
        if txn_id and txn_id != flagged and rs >= 0.5:
            if txn_id not in state["affected_txn_ids"]:
                state["affected_txn_ids"].append(txn_id)

    # Detect card testing pattern: 3+ small online txns in 1 hour + larger purchase
    _detect_card_testing(state, card_evidence)

    # Tool 2: Device neighbors — check for shared device profiles
    device_key = state.get("_device_key", "")
    if device_key:
        device_evidence = tg_tools.device_neighbors(device_key)
        state["evidence"].append(_to_evidence(device_evidence))
        # Track connected cards and device profiles
        found_cards = device_evidence.get("_card_ids", [])
        state["connected_card_ids"] = list(set(
            state["connected_card_ids"] + found_cards
        ))
        # Remove the case's own card from connected
        if state["card_id"] in state["connected_card_ids"]:
            state["connected_card_ids"].remove(state["card_id"])

        # If device is shared across cards, set shared element description
        if state["connected_card_ids"]:
            state["_evidence_bundle"] = state.get("_evidence_bundle", {})
            state["_evidence_bundle"]["shared_element_description"] = (
                f"device profile {device_key}"
            )
            # Also check for closed cases linked to this device
            closed_cases = device_evidence.get("_closed_case_ids", [])
            if closed_cases:
                state["_evidence_bundle"]["shared_element_description"] += (
                    f" (linked to closed case(s): {', '.join(closed_cases)})"
                )

    # Tool 3: Region cluster — check for out-of-region use
    region_code = state.get("_region_code", "")
    if region_code:
        region_evidence = tg_tools.region_cluster(region_code, window_days=30)
        state["evidence"].append(_to_evidence(region_evidence))

    # Tool 4: Customer baseline — historical spending patterns
    customer_evidence = tg_tools.customer_baseline(state["customer_id"])
    state["evidence"].append(_to_evidence(customer_evidence))

    state["tool_calls"] = tg_tools.tool_call_count
    return state


def retrieve_memory(state: AgentState, tg_tools: TigerGraphTools) -> AgentState:
    """RETRIEVE_MEMORY: Vector search + graph traversal for similar prior cases."""
    _log_node(state, "RETRIEVE_MEMORY", {})

    # Graph traversal: find closed cases touching this card or connected entities
    entity_ids_to_search = [state["card_id"]] + state.get("connected_card_ids", [])
    case_evidence = tg_tools.closed_case_lookup(entity_ids_to_search)
    state["evidence"].append(_to_evidence(case_evidence))

    prior_cases = case_evidence.get("_cases", [])
    state["similar_prior_cases"] = [c["case_id"] for c in prior_cases if c.get("case_id")]
    state["_similar_cases"] = prior_cases

    # Vector search: find similar patterns in closed case notes
    query_text = state.get("trigger_text", f"Fraud investigation for card {state['card_id']}")
    vector_evidence = tg_tools.vector_search(
        query_text=query_text,
        chunk_type="ClosedCase",
        k=3,
    )
    state["evidence"].append(_to_evidence(vector_evidence))

    # Vector search for relevant policy rules
    policy_evidence = tg_tools.vector_search(
        query_text=query_text,
        chunk_type="PolicyChunk",
        k=3,
    )
    state["evidence"].append(_to_evidence(policy_evidence))

    # Vector search for regulatory document context (for potential SAR writing)
    reg_evidence = tg_tools.vector_search(
        query_text="suspicious activity report fraud narrative",
        chunk_type="RegDoc",
        k=3,
    )
    state["_reg_doc_chunks"] = [c["text"] for c in reg_evidence.get("_chunks", [])]

    state["tool_calls"] = tg_tools.tool_call_count
    return state


def assess_node(state: AgentState, groq_client: GroqClient) -> AgentState:
    """
    ASSESS: Groq LLM call grounded ONLY on the evidence list already gathered.

    Outputs: pattern, pattern_description (if undocumented), fraud_probability, rationale.
    This is one of only two nodes that calls the LLM.
    """
    _log_node(state, "ASSESS", {})

    result = groq_client.assess_evidence(
        evidence_list=state["evidence"],
        case_context=state.get("_case_context", {}),
        similar_cases=state.get("_similar_cases", []),
    )

    state["pattern"] = result.get("pattern", "none")
    state["pattern_description"] = result.get("pattern_description", "")
    state["fraud_probability"] = result.get("fraud_probability", 0.5)
    state["summary"] = result.get("summary", "")

    # Fix 5: Don't use 'undocumented' when there's simply no data.
    # 'undocumented' means coordinated/repeated abuse that fits no known pattern.
    # Having no transaction history is not an undocumented pattern — it's just
    # missing data.  Downgrade to 'none' unless the description clearly
    # describes a real novel pattern of abuse.
    if state["pattern"] == "undocumented":
        desc_lower = state["pattern_description"].lower()
        no_data_phrases = [
            "no prior", "no historical", "no transaction history",
            "first observed", "first recorded", "first-time",
            "first time", "no baseline", "no activity", "lack of",
            "insufficient data", "no record",
        ]
        if any(phrase in desc_lower for phrase in no_data_phrases):
            state["pattern"] = "none"
            state["pattern_description"] = ""

    # Update exposure: sum of affected transaction amounts
    _compute_exposure(state)

    state["tokens"] = groq_client.total_tokens
    return state


def single_signal_check(state: AgentState, groq_client: GroqClient) -> AgentState:
    """
    SINGLE_SIGNAL_CHECK: Determine if the case rests on a single signal only.
    Uses the small/cheap LLM model.
    """
    _log_node(state, "SINGLE_SIGNAL_CHECK", {})

    is_single = groq_client.classify_single_signal(state["evidence"])
    state["_evidence_bundle"] = state.get("_evidence_bundle", {})
    state["_evidence_bundle"]["is_single_signal"] = is_single
    state["_evidence_bundle"]["n_evidence_sources"] = len(state["evidence"])

    state["tokens"] = groq_client.total_tokens
    return state


def decide_actions_initial_node(state: AgentState) -> AgentState:
    """
    DECIDE_ACTIONS_INITIAL: PolicyEngine.decide_initial().
    For the initial recommendation, we don't factor in customer replies yet
    (even if the trigger was a customer_report). This creates the action
    evolution the README requires: initial shows pre-evidence actions,
    final shows post-evidence actions.
    """
    _log_node(state, "DECIDE_ACTIONS_INITIAL", {})

    # Temporarily clear customer reply for initial decision
    saved_reply = state.get("_customer_reply")
    state["_customer_reply"] = None

    bundle = _build_evidence_bundle(state)
    actions = decide_initial(
        evidence=bundle,
        probability=state["fraud_probability"],
        pattern=state["pattern"],
    )

    # Restore customer reply
    state["_customer_reply"] = saved_reply

    state["initial_actions"] = [
        {"action": a.action, "route": a.route, "reason": a.reason}
        for a in actions
    ]

    # Determine if we need more evidence
    needs_verify = any(a.action in ("VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH") for a in actions)
    ambiguous = 0.30 < state["fraud_probability"] < 0.70 and bundle.is_single_signal

    # For customer_report cases, the customer has already spoken — always go
    # through the evidence request path so decide_final applies R2.
    is_customer_report = state.get("trigger_type") == "customer_report"

    state["_needs_more_evidence"] = needs_verify or ambiguous or is_customer_report

    state["_current_step"] = state.get("_current_step", 0) + 1
    return state


def need_more_evidence_check(state: AgentState) -> str:
    """Conditional edge: should we request more evidence?"""
    if state.get("_needs_more_evidence", False):
        return "yes"
    return "no"


def request_evidence(state: AgentState, supabase_client: Any) -> AgentState:
    """
    REQUEST_EVIDENCE: Log evidence request, pull simulated response from Supabase.
    For customer_report cases, the denial is already recorded in trigger_node,
    so we skip to avoid duplication.
    """
    _log_node(state, "REQUEST_EVIDENCE", {})

    # For customer_report cases, the denial evidence was already recorded
    # in trigger_node. Skip generating a new request.
    if state.get("trigger_type") == "customer_report":
        # Customer reply is already "denied" from trigger_node
        return state

    # Determine the type of evidence request
    has_verify = any(
        a["action"] == "VERIFY_WITH_CUSTOMER"
        for a in state.get("initial_actions", [])
    )
    has_stepup = any(
        a["action"] == "STEP_UP_AUTH"
        for a in state.get("initial_actions", [])
    )

    request_type = "customer_validation" if has_verify else "step_up_auth" if has_stepup else "analyst_info"

    # Pull simulated response from Supabase
    assumed_response = ""
    try:
        if supabase_client:
            result = supabase_client.table("simulated_responses").select("*").eq(
                "case_id", state["case_id"]
            ).execute()
            if result.data:
                assumed_response = result.data[0].get("assumed_response", "")
                request_type = result.data[0].get("response_type", request_type)
    except Exception as e:
        logger.warning(f"Failed to fetch simulated response: {e}")

    if not assumed_response:
        # Generate a reasonable default based on trigger type
        assumed_response = (
            f"Customer {state['customer_id']} states they did not recognize "
            f"the transaction on card {state['card_id']}."
        )
        state["_customer_reply"] = "denied"

    # Parse customer reply from assumed response
    response_lower = assumed_response.lower()
    if "did not" in response_lower or "never" in response_lower or "denied" in response_lower:
        state["_customer_reply"] = "denied"
    elif "confirmed" in response_lower or "recognize" in response_lower and "not" not in response_lower:
        state["_customer_reply"] = "confirmed"
    elif "no reply" in response_lower or "no response" in response_lower:
        state["_customer_reply"] = None
        state["_evidence_bundle"] = state.get("_evidence_bundle", {})
        state["_evidence_bundle"]["no_reply_24h"] = True

    # Record the evidence request
    state["evidence_requests"].append({
        "type": request_type,
        "asked_after_step": state.get("_current_step", 4),
        "assumed_response": assumed_response,
    })

    # Add customer evidence
    state["evidence"].append({
        "claim": assumed_response,
        "source": "customer",
        "ref": f"evidence_request:{len(state['evidence_requests'])}",
        "entity_ids": [],
    })

    return state


def re_assess_node(state: AgentState, groq_client: GroqClient) -> AgentState:
    """RE-ASSESS: Updated Groq call with new evidence (customer reply, etc.)."""
    _log_node(state, "RE_ASSESS", {})

    result = groq_client.assess_evidence(
        evidence_list=state["evidence"],
        case_context=state.get("_case_context", {}),
        similar_cases=state.get("_similar_cases", []),
    )

    # Update probability and summary with new evidence
    state["fraud_probability"] = result.get("fraud_probability", state["fraud_probability"])
    state["summary"] = result.get("summary", state["summary"])

    # Pattern may be refined with new evidence
    new_pattern = result.get("pattern", state["pattern"])
    if new_pattern != "none":
        state["pattern"] = new_pattern
        state["pattern_description"] = result.get("pattern_description", "")

    # Fix 5: Same undocumented-pattern guard as in assess_node
    if state["pattern"] == "undocumented":
        desc_lower = state["pattern_description"].lower()
        no_data_phrases = [
            "no prior", "no historical", "no transaction history",
            "first observed", "first recorded", "first-time",
            "first time", "no baseline", "no activity", "lack of",
            "insufficient data", "no record",
        ]
        if any(phrase in desc_lower for phrase in no_data_phrases):
            state["pattern"] = "none"
            state["pattern_description"] = ""

    _compute_exposure(state)
    state["tokens"] = groq_client.total_tokens
    return state


def decide_actions_final_node(state: AgentState) -> AgentState:
    """
    DECIDE_ACTIONS_FINAL: PolicyEngine.decide_final() after evidence returns.
    """
    _log_node(state, "DECIDE_ACTIONS_FINAL", {})

    bundle = _build_evidence_bundle(state)
    actions = decide_final(
        evidence=bundle,
        probability=state["fraud_probability"],
        pattern=state["pattern"],
        customer_reply=state.get("_customer_reply"),
    )

    state["final_actions"] = [
        {"action": a.action, "route": a.route, "reason": a.reason}
        for a in actions
    ]

    # Determine what changed
    initial_set = {a["action"] for a in state.get("initial_actions", [])}
    final_set = {a["action"] for a in state["final_actions"]}
    if initial_set == final_set:
        state["what_changed"] = "nothing"
    else:
        added = final_set - initial_set
        removed = initial_set - final_set
        parts = []
        if added:
            parts.append(f"Added: {', '.join(sorted(added))}")
        if removed:
            parts.append(f"Removed: {', '.join(sorted(removed))}")
        customer_reply = state.get("_customer_reply", "")
        if customer_reply:
            parts.append(f"Customer reply: {customer_reply}")
        state["what_changed"] = ". ".join(parts) + "."

    return state


def copy_initial_to_final(state: AgentState) -> AgentState:
    """When no more evidence needed, final = initial."""
    state["final_actions"] = deepcopy(state.get("initial_actions", []))
    state["what_changed"] = "nothing"
    _log_node(state, "COPY_INITIAL_TO_FINAL", {})
    return state


def stop_check_node(state: AgentState) -> AgentState:
    """
    STOP_CHECK: Determine when to stop investigating.

    Stop when:
    - Probability >= 0.85 or <= 0.15 with >= 2 evidence sources
    - Verification response settled the question
    - Further steps unlikely to change decision
    """
    _log_node(state, "STOP_CHECK", {})

    prob = state["fraud_probability"]
    n_evidence = len(state["evidence"])
    customer_reply = state.get("_customer_reply")

    if prob >= 0.85 and n_evidence >= 2:
        state["stop_reason"] = (
            f"Fraud probability {prob:.2f} is at or above 0.85, supported by "
            f"{n_evidence} evidence sources. Investigation conclusive."
        )
        state["verdict"] = "fraud"
        state["status"] = "closed_fraud"
    elif prob <= 0.15 and n_evidence >= 2:
        state["stop_reason"] = (
            f"Fraud probability {prob:.2f} is at or below 0.15, supported by "
            f"{n_evidence} evidence sources. Transaction appears legitimate."
        )
        state["verdict"] = "legitimate"
        state["status"] = "closed_legitimate"
    elif customer_reply == "confirmed":
        state["stop_reason"] = (
            "Customer confirmed the transaction. No further investigation needed."
        )
        state["verdict"] = "legitimate"
        state["status"] = "closed_legitimate"
        state["fraud_probability"] = min(state["fraud_probability"], 0.10)
        state["affected_txn_ids"] = []
        state["exposure_usd"] = 0.0
    elif customer_reply == "denied":
        # Fix 2: R2 — customer denied the transaction. This is strong evidence
        # of fraud regardless of probability. Boost probability if needed.
        if prob < 0.70:
            state["fraud_probability"] = max(prob, 0.72)
            prob = state["fraud_probability"]
        state["stop_reason"] = (
            f"Customer denied the transaction (R2). Fraud probability adjusted to "
            f"{prob:.2f}. Sufficient evidence for fraud determination."
        )
        state["verdict"] = "fraud"
        state["status"] = "closed_fraud"
    elif prob >= 0.70:
        state["stop_reason"] = (
            f"Fraud probability {prob:.2f} is above the decision threshold. "
            f"Further investigation unlikely to change the outcome."
        )
        state["verdict"] = "fraud"
        state["status"] = "closed_fraud"
    elif 0.30 <= prob < 0.70:
        state["stop_reason"] = (
            f"Fraud probability {prob:.2f} is in the uncertain range. "
            f"Evidence gathered is sufficient for escalation."
        )
        state["verdict"] = "uncertain"
        state["status"] = "escalated"
    else:
        state["stop_reason"] = (
            f"Fraud probability {prob:.2f} is low. "
            f"No strong indicators of fraud found."
        )
        state["verdict"] = "legitimate"
        state["status"] = "closed_legitimate"

    # Fix 3+4: For fraud verdicts, always populate affected_txn_ids and
    # first_suspicious_txn_id with at least the flagged transaction.
    if state["verdict"] == "fraud":
        flagged = state.get("flagged_txn_id", "")
        if flagged and flagged not in state.get("affected_txn_ids", []):
            state["affected_txn_ids"] = [flagged] + state.get("affected_txn_ids", [])
        if not state.get("first_suspicious_txn_id"):
            state["first_suspicious_txn_id"] = flagged
        # Recompute exposure now that we have affected txns
        _compute_exposure(state)
        # If exposure is still 0 but we have a flagged txn amount, use it
        if state["exposure_usd"] == 0.0:
            ctx = state.get("_case_context", {})
            amount = ctx.get("amount", 0)
            if amount:
                state["exposure_usd"] = round(abs(amount), 2)

    return state


def sar_decision_node(state: AgentState) -> AgentState:
    """SAR_DECISION: Deterministic, per Section 3a rules."""
    _log_node(state, "SAR_DECISION", {})

    bundle = _build_evidence_bundle(state)
    should_file, reason = sar_decision(
        verdict=state["verdict"],
        pattern=state["pattern"],
        exposure_usd=state["exposure_usd"],
        shared_origin=bundle.shared_origin_detected,
    )

    state["sar_file"] = should_file
    state["sar_reason"] = reason

    # Ensure FILE_REPORT is in final actions iff sar_file is true
    final_actions = state.get("final_actions", [])
    has_file_report = any(a["action"] == "FILE_REPORT" for a in final_actions)

    if should_file and not has_file_report:
        final_actions.append({
            "action": "FILE_REPORT",
            "route": "L2",
            "reason": reason,
        })
        state["final_actions"] = final_actions
    elif not should_file and has_file_report:
        state["final_actions"] = [a for a in final_actions if a["action"] != "FILE_REPORT"]

    return state


def sar_write_check(state: AgentState) -> str:
    """Conditional: should we write a SAR narrative?"""
    return "write_sar" if state.get("sar_file", False) else "skip_sar"


def sar_write_node(state: AgentState, groq_client: GroqClient) -> AgentState:
    """SAR_WRITE: Groq call to write the SAR narrative, grounded on FinCEN docs."""
    _log_node(state, "SAR_WRITE", {})

    narrative = groq_client.write_sar_narrative(
        case_detail={
            "case_id": state["case_id"],
            "card_id": state["card_id"],
            "customer_id": state["customer_id"],
            "pattern": state["pattern"],
            "exposure_usd": state["exposure_usd"],
            "affected_txn_ids": state["affected_txn_ids"],
            "verdict": state["verdict"],
        },
        evidence_list=state["evidence"],
        reg_doc_chunks=state.get("_reg_doc_chunks", []),
    )

    state["sar_narrative"] = narrative
    state["sar_subjects"] = [state["customer_id"], state["card_id"]] + state.get("connected_card_ids", [])
    state["sar_total_amount_usd"] = state["exposure_usd"]

    # Compute activity dates from affected transactions
    dates = _extract_activity_dates(state)
    state["sar_activity_dates"] = dates

    state["tokens"] = groq_client.total_tokens
    return state


def write_case_to_graph(state: AgentState, tg_tools: TigerGraphTools, supabase_client: Any) -> AgentState:
    """WRITE_CASE_TO_GRAPH: Write case to TigerGraph + mirror to Supabase."""
    _log_node(state, "WRITE_CASE_TO_GRAPH", {})

    answer = _build_answer_file(state)

    # Write to TigerGraph
    result = tg_tools.write_case({
        "case_id": state["case_id"],
        "case": answer["case"],
        "next_best_actions": answer["next_best_actions"],
        "_flagged_txn_id": state["flagged_txn_id"],
    })

    state["written_to_graph"] = result.get("written_to_graph", False)
    state["graph_case_id"] = result.get("graph_case_id", "")
    state["tool_calls"] = tg_tools.tool_call_count

    # Mirror to Supabase
    try:
        if supabase_client:
            supabase_client.table("cases").upsert({
                "case_id": state["case_id"],
                "status": state["status"],
                "verdict": state["verdict"],
                "fraud_probability": state["fraud_probability"],
                "pattern": state["pattern"],
                "exposure_usd": state["exposure_usd"],
                "summary": state["summary"],
                "payload": json.dumps(answer, default=str),
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
    except Exception as e:
        logger.error(f"Failed to mirror case to Supabase: {e}")

    return state


def emit_answer_file(state: AgentState) -> AgentState:
    """EMIT_ANSWER_FILE: Build and validate final answer, write to disk."""
    _log_node(state, "EMIT_ANSWER_FILE", {})

    state["latency_s"] = round(time.time() - state.get("start_time", time.time()), 1)

    answer = _build_answer_file(state)

    # Validate with Pydantic
    try:
        validated = AnswerFile.model_validate(answer)
        answer_json = validated.model_dump(mode="json")
    except Exception as e:
        logger.error(f"Answer validation failed for {state['case_id']}: {e}")
        # Still write the file but mark the error
        answer_json = answer
        answer_json["_validation_error"] = str(e)

    # Write to disk
    os.makedirs("cases", exist_ok=True)
    filepath = os.path.join("cases", f"{state['case_id']}.json")
    with open(filepath, "w") as f:
        json.dump(answer_json, f, indent=2, default=str)

    logger.info(f"Answer file written: {filepath}")
    state["_answer_file"] = answer_json
    return state


# ── Graph builder ────────────────────────────────────────────────────────────

def build_investigation_graph(
    tg_tools: TigerGraphTools,
    groq_client: GroqClient,
    supabase_client: Any = None,
) -> StateGraph:
    """
    Build the LangGraph state machine implementing the 8-step investigation flow.

    Returns a compiled StateGraph ready to invoke.
    """

    # Create node functions with dependencies injected
    def _trigger(state: AgentState) -> AgentState:
        return trigger_node(state)

    def _load_context(state: AgentState) -> AgentState:
        return load_case_context(state, tg_tools)

    def _gather(state: AgentState) -> AgentState:
        return gather_evidence(state, tg_tools)

    def _memory(state: AgentState) -> AgentState:
        return retrieve_memory(state, tg_tools)

    def _assess(state: AgentState) -> AgentState:
        return assess_node(state, groq_client)

    def _signal_check(state: AgentState) -> AgentState:
        return single_signal_check(state, groq_client)

    def _decide_initial(state: AgentState) -> AgentState:
        return decide_actions_initial_node(state)

    def _request_ev(state: AgentState) -> AgentState:
        return request_evidence(state, supabase_client)

    def _re_assess(state: AgentState) -> AgentState:
        return re_assess_node(state, groq_client)

    def _decide_final(state: AgentState) -> AgentState:
        return decide_actions_final_node(state)

    def _copy_final(state: AgentState) -> AgentState:
        return copy_initial_to_final(state)

    def _stop(state: AgentState) -> AgentState:
        return stop_check_node(state)

    def _sar_decide(state: AgentState) -> AgentState:
        return sar_decision_node(state)

    def _sar_write(state: AgentState) -> AgentState:
        return sar_write_node(state, groq_client)

    def _write_graph(state: AgentState) -> AgentState:
        return write_case_to_graph(state, tg_tools, supabase_client)

    def _emit(state: AgentState) -> AgentState:
        return emit_answer_file(state)

    # Build the graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("trigger", _trigger)
    workflow.add_node("load_case_context", _load_context)
    workflow.add_node("gather_evidence", _gather)
    workflow.add_node("retrieve_memory", _memory)
    workflow.add_node("assess", _assess)
    workflow.add_node("single_signal_check", _signal_check)
    workflow.add_node("decide_actions_initial", _decide_initial)
    workflow.add_node("request_evidence", _request_ev)
    workflow.add_node("re_assess", _re_assess)
    workflow.add_node("decide_actions_final", _decide_final)
    workflow.add_node("copy_initial_to_final", _copy_final)
    workflow.add_node("stop_check", _stop)
    workflow.add_node("sar_decision", _sar_decide)
    workflow.add_node("sar_write", _sar_write)
    workflow.add_node("write_case_to_graph", _write_graph)
    workflow.add_node("emit_answer_file", _emit)

    # Set entry point
    workflow.set_entry_point("trigger")

    # Linear edges
    workflow.add_edge("trigger", "load_case_context")
    workflow.add_edge("load_case_context", "gather_evidence")
    workflow.add_edge("gather_evidence", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "assess")
    workflow.add_edge("assess", "single_signal_check")
    workflow.add_edge("single_signal_check", "decide_actions_initial")

    # Conditional: need more evidence?
    workflow.add_conditional_edges(
        "decide_actions_initial",
        need_more_evidence_check,
        {
            "yes": "request_evidence",
            "no": "copy_initial_to_final",
        },
    )

    # Evidence request path
    workflow.add_edge("request_evidence", "re_assess")
    workflow.add_edge("re_assess", "decide_actions_final")
    workflow.add_edge("decide_actions_final", "stop_check")

    # No evidence needed path
    workflow.add_edge("copy_initial_to_final", "stop_check")

    # After stop check
    workflow.add_edge("stop_check", "sar_decision")

    # Conditional: write SAR?
    workflow.add_conditional_edges(
        "sar_decision",
        sar_write_check,
        {
            "write_sar": "sar_write",
            "skip_sar": "write_case_to_graph",
        },
    )

    workflow.add_edge("sar_write", "write_case_to_graph")
    workflow.add_edge("write_case_to_graph", "emit_answer_file")
    workflow.add_edge("emit_answer_file", END)

    return workflow.compile()


# ── Helper functions ─────────────────────────────────────────────────────────

def _to_evidence(tool_result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a tool result to Answer Format evidence shape."""
    return {
        "claim": tool_result.get("claim", ""),
        "source": tool_result.get("source", "graph"),
        "ref": tool_result.get("ref", ""),
        "entity_ids": tool_result.get("entity_ids", []),
    }


def _build_evidence_bundle(state: AgentState) -> EvidenceBundle:
    """Build an EvidenceBundle from current state for the policy engine."""
    eb_dict = state.get("_evidence_bundle", {})

    return EvidenceBundle(
        fraud_probability=state.get("fraud_probability", 0.5),
        exposure_usd=state.get("exposure_usd", 0.0),
        is_single_signal=eb_dict.get("is_single_signal", False),
        n_evidence_sources=len(state.get("evidence", [])),
        card_testing_detected=state.get("pattern") == "card_testing",
        large_purchase_cleared=eb_dict.get("large_purchase_cleared", False),
        shared_origin_detected=len(state.get("connected_card_ids", [])) > 0,
        shared_element_description=eb_dict.get("shared_element_description", ""),
        customer_reply=state.get("_customer_reply"),
        no_reply_24h=eb_dict.get("no_reply_24h", False),
        is_recurring_disputed_but_matches_pattern=eb_dict.get(
            "is_recurring_disputed_but_matches_pattern", False
        ),
        coordinated_abuse=eb_dict.get("coordinated_abuse", False),
        n_cards_with_confirmed_fraud=eb_dict.get("n_cards_with_confirmed_fraud", 0),
        credentials_compromised=eb_dict.get("credentials_compromised", False),
        verdict_uncertain=state.get("verdict") == "uncertain",
        evidence_conflicts=eb_dict.get("evidence_conflicts", False),
        connected_card_ids=state.get("connected_card_ids", []),
        connected_device_profiles=state.get("connected_device_profiles", []),
    )


def _detect_card_testing(state: AgentState, card_evidence: Dict[str, Any]) -> None:
    """Detect card testing pattern: 3+ small online txns in 1h + larger purchase."""
    details = card_evidence.get("_details", [])
    if len(details) < 4:
        return

    # Sort by timestamp
    sorted_txns = sorted(details, key=lambda x: str(x.get("ts", "")))

    # Look for 3+ small txns followed by a larger one
    small_txns = [t for t in sorted_txns if t.get("amount", 0) < 5 and t.get("channel") == "online"]
    large_txns = [t for t in sorted_txns if t.get("amount", 0) >= 100]

    if len(small_txns) >= 3 and large_txns:
        state["_evidence_bundle"] = state.get("_evidence_bundle", {})
        state["_evidence_bundle"]["large_purchase_cleared"] = True
        state["affected_txn_ids"] = [t["txn_id"] for t in small_txns + large_txns]
        state["first_suspicious_txn_id"] = small_txns[0].get("txn_id", "")


def _compute_exposure(state: AgentState) -> None:
    """Compute exposure_usd from affected transactions."""
    txn_details = state.get("_txn_details", [])
    affected = state.get("affected_txn_ids", [])

    if affected and txn_details:
        total = sum(
            abs(t.get("amount", 0))
            for t in txn_details
            if t.get("txn_id") in affected
        )
        state["exposure_usd"] = round(total, 2)
    elif affected:
        # If we don't have details, at least include the flagged txn amount
        ctx = state.get("_case_context", {})
        amount = ctx.get("amount", 0)
        state["exposure_usd"] = round(abs(amount), 2)


def _extract_activity_dates(state: AgentState) -> List[str]:
    """Extract first and last activity dates for SAR."""
    txn_details = state.get("_txn_details", [])
    affected = state.get("affected_txn_ids", [])

    dates = []
    for t in txn_details:
        if t.get("txn_id") in affected:
            ts = str(t.get("ts", ""))
            if ts:
                dates.append(ts[:10])  # YYYY-MM-DD

    if not dates:
        # Fallback to case opened_at
        opened = state.get("opened_at", "")
        if opened:
            dates = [opened[:10]]

    if dates:
        dates.sort()
        return [dates[0], dates[-1]]
    return []


def _build_answer_file(state: AgentState) -> Dict[str, Any]:
    """Build the complete answer file dict from state."""
    return {
        "case_id": state["case_id"],
        "case": {
            "status": state.get("status", "open"),
            "verdict": state.get("verdict", "uncertain"),
            "fraud_probability": state.get("fraud_probability", 0.5),
            "pattern": state.get("pattern", "none"),
            "pattern_description": state.get("pattern_description", ""),
            "affected_txn_ids": state.get("affected_txn_ids", []),
            "first_suspicious_txn_id": state.get("first_suspicious_txn_id", ""),
            "connected_card_ids": state.get("connected_card_ids", []),
            "connected_device_profiles": state.get("connected_device_profiles", []),
            "exposure_usd": state.get("exposure_usd", 0.0),
            "evidence": state.get("evidence", []),
            "similar_prior_cases": state.get("similar_prior_cases", []),
            "summary": state.get("summary", ""),
            "written_to_graph": state.get("written_to_graph", False),
            "graph_case_id": state.get("graph_case_id", ""),
        },
        "evidence_requests": state.get("evidence_requests", []),
        "next_best_actions": {
            "initial": state.get("initial_actions", []),
            "final": state.get("final_actions", []),
            "what_changed": state.get("what_changed", "nothing"),
        },
        "sar": {
            "file": state.get("sar_file", False),
            "reason": state.get("sar_reason", ""),
            "narrative": state.get("sar_narrative", ""),
            "subjects": state.get("sar_subjects", []),
            "total_amount_usd": state.get("sar_total_amount_usd", 0.0),
            "activity_dates": state.get("sar_activity_dates", []),
        },
        "stop_reason": state.get("stop_reason", ""),
        "tool_calls": state.get("tool_calls", 0),
        "tokens": state.get("tokens", 0),
        "latency_s": state.get("latency_s", 0.0),
    }


def _log_node(state: AgentState, node_name: str, details: Dict[str, Any]) -> None:
    """Log node execution for the trace API."""
    trace = state.get("_node_trace", [])
    trace.append({
        "node": node_name,
        "timestamp": datetime.utcnow().isoformat(),
        "step": len(trace) + 1,
        "details": details,
    })
    state["_node_trace"] = trace
    logger.info(f"[{state.get('case_id', '?')}] Node: {node_name}")
