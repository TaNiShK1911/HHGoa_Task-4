"""
Deterministic Policy Engine — Section 6 of the implementation plan.

Pure functions, zero LLM calls. Literal transcription of Fraud Policy rules
R1–R10 from the README. Every action/route decision comes from here, never
from the LLM.

Unit tests: tests/test_policy_engine.py (one dedicated test per rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Action:
    """A recommended action with approval route and policy citation."""
    action: str
    route: str
    reason: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Action):
            return NotImplemented
        return (self.action, self.route, self.reason) == (
            other.action,
            other.route,
            other.reason,
        )

    def __hash__(self) -> int:
        return hash((self.action, self.route, self.reason))

    def __repr__(self) -> str:
        return f"Action({self.action!r}, {self.route!r}, {self.reason!r})"


@dataclass
class EvidenceBundle:
    """
    Structured evidence gathered during investigation.

    This is populated by the GATHER_EVIDENCE and RETRIEVE_MEMORY nodes of
    the LangGraph state machine, then consumed by the policy engine.
    """
    # Core metrics
    fraud_probability: float = 0.0
    exposure_usd: float = 0.0

    # Signal analysis
    is_single_signal: bool = False
    n_evidence_sources: int = 0

    # Pattern-specific flags
    card_testing_detected: bool = False
    large_purchase_cleared: bool = False  # For R5: purchase > $100 already cleared

    # Shared origin (R6)
    shared_origin_detected: bool = False
    shared_element_description: str = ""

    # Customer response (R2, R3, R4)
    customer_reply: Optional[str] = None  # "denied" | "confirmed" | None
    no_reply_24h: bool = False

    # Disputed-but-legitimate (R7)
    is_recurring_disputed_but_matches_pattern: bool = False

    # Undocumented pattern (R9)
    coordinated_abuse: bool = False

    # Multi-card compromise (R10)
    n_cards_with_confirmed_fraud: int = 0
    credentials_compromised: bool = False

    # Uncertainty (R8)
    verdict_uncertain: bool = False
    evidence_conflicts: bool = False

    # Connected entities
    connected_card_ids: List[str] = field(default_factory=list)
    connected_device_profiles: List[str] = field(default_factory=list)


# ── Approval routing ─────────────────────────────────────────────────────────

def route_for_exposure(exposure_usd: float) -> str:
    """
    Determine approval route based on exposure amount.

    Per Fraud Policy Section 2:
    - L1 (team lead): BLOCK_CARD when exposure ≤ $2,500
    - L2 (fraud manager): BLOCK_CARD when exposure > $2,500
    """
    return "L1" if exposure_usd <= 2500 else "L2"


# ── Core policy functions ─────────────────────────────────────────────────────

def decide_initial(
    evidence: EvidenceBundle,
    probability: float,
    pattern: str,
) -> List[Action]:
    """
    Determine initial next-best-actions BEFORE any requested evidence returns.

    Applies rules R1, R5, R6, R7, R8, R9, R10 as applicable.
    Rules R2, R3, R4 require customer reply and are only in decide_final().
    """
    actions: List[Action] = []

    # R1: Verify before blocking on a weak signal
    # If case rests on single signal AND probability < 0.70, verify first
    if evidence.is_single_signal and probability < 0.70:
        actions.append(
            Action("VERIFY_WITH_CUSTOMER", "auto", "R1: single signal with probability below 0.70, verify before blocking")
        )

    # R5: Card testing
    # 3+ small online in 1h + larger purchase → DECLINE + STEP_UP_AUTH
    # If purchase > $100 already cleared → BLOCK_CARD
    if pattern == "card_testing" or evidence.card_testing_detected:
        actions.append(
            Action("DECLINE_TRANSACTION", "L1", "R5: card testing sequence detected")
        )
        actions.append(
            Action("STEP_UP_AUTH", "auto", "R5: card testing — require additional authentication")
        )
        if evidence.large_purchase_cleared:
            actions.append(
                Action(
                    "BLOCK_CARD",
                    route_for_exposure(evidence.exposure_usd),
                    "R5: card testing with purchase over $100 already cleared",
                )
            )

    # R6: Shared origin
    # Several cards from same device/region/email → CREATE_CASE + FILE_REPORT + MONITOR_CONNECTED_CARDS
    if evidence.shared_origin_detected:
        actions.append(
            Action("CREATE_CASE", "auto", f"R6: shared origin detected — {evidence.shared_element_description}")
        )
        actions.append(
            Action("FILE_REPORT", "L2", f"R6: shared origin — {evidence.shared_element_description}")
        )
        actions.append(
            Action("MONITOR_CONNECTED_CARDS", "auto", f"R6: monitor cards sharing {evidence.shared_element_description}")
        )

    # R7: Disputed but legitimate (recurring charge matching pattern)
    if evidence.is_recurring_disputed_but_matches_pattern:
        # R7 replaces other actions for this case
        actions = [
            Action("CREATE_CASE", "auto", "R7: disputed charge matches recurring pattern"),
            Action("VERIFY_WITH_CUSTOMER", "auto", "R7: verify recurring charge dispute"),
            Action("WARN_CUSTOMER", "auto", "R7: warn about recurring charge pattern"),
        ]
        return _dedupe(actions)

    # R9: Undocumented patterns with coordinated abuse
    if pattern == "undocumented" and evidence.coordinated_abuse:
        actions.append(
            Action("CREATE_CASE", "auto", "R9: undocumented pattern with coordinated abuse")
        )
        actions.append(
            Action("FILE_REPORT", "L2", "R9: undocumented coordinated activity requires filing")
        )
        actions.append(
            Action("ESCALATE_TO_ANALYST", "auto", "R9: undocumented pattern needs analyst review")
        )

    # R8: Escalate when uncertain and exposed
    if evidence.verdict_uncertain and evidence.exposure_usd > 500:
        actions.append(
            Action("ESCALATE_TO_ANALYST", "auto", "R8: uncertain verdict with exposure exceeding $500")
        )
    if evidence.evidence_conflicts and evidence.exposure_usd > 500:
        actions.append(
            Action("ESCALATE_TO_ANALYST", "auto", "R8: conflicting evidence with exposure exceeding $500")
        )

    # If no specific rule triggered and probability is low, allow transaction
    if not actions and probability <= 0.15 and evidence.n_evidence_sources >= 2:
        actions.append(
            Action("ALLOW_TRANSACTION", "auto", "Low fraud probability with multiple supporting evidence sources")
        )
        actions.append(
            Action("CLOSE_NO_FRAUD", "auto", "No fraud indicators found")
        )

    # If no specific rule triggered and probability is moderate, monitor
    if not actions and 0.15 < probability < 0.70:
        actions.append(
            Action("MONITOR_CARD", "auto", "Moderate risk — monitor card activity")
        )
        if evidence.is_single_signal:
            actions.append(
                Action("VERIFY_WITH_CUSTOMER", "auto", "R1: single signal, verify before further action")
            )

    # If no specific rule triggered and probability is high, create case
    if not actions and probability >= 0.70:
        actions.append(
            Action("CREATE_CASE", "auto", "High fraud probability warrants case creation")
        )
        if evidence.exposure_usd > 1000 or evidence.shared_origin_detected:
            actions.append(
                Action("FILE_REPORT", "L2", "R2/R6: high probability with significant exposure or shared origin")
            )
        actions.append(
            Action(
                "BLOCK_CARD",
                route_for_exposure(evidence.exposure_usd),
                "High fraud probability warrants card block",
            )
        )

    return _dedupe(actions)


def decide_final(
    evidence: EvidenceBundle,
    probability: float,
    pattern: str,
    customer_reply: Optional[str],
) -> List[Action]:
    """
    Determine final next-best-actions AFTER any requested evidence returns.

    This applies rules R2, R3, R4 based on customer reply, then layering
    R5–R10 on top as applicable.
    """
    actions: List[Action] = []

    # R2: Customer denies the transaction
    if customer_reply == "denied":
        actions.append(
            Action(
                "BLOCK_CARD",
                route_for_exposure(evidence.exposure_usd),
                "R2: customer denied the transaction",
            )
        )
        actions.append(
            Action("CREATE_CASE", "auto", "R2: customer denial requires case creation")
        )
        # Add FILE_REPORT if exposure > $1,000 OR shared origin
        if evidence.exposure_usd > 1000 or evidence.shared_origin_detected:
            actions.append(
                Action("FILE_REPORT", "L2", "R2: customer denial with exposure >$1,000 or shared origin")
            )

    # R3: Customer confirms the transaction
    elif customer_reply == "confirmed":
        actions.append(
            Action("CLOSE_NO_FRAUD", "auto", "R3: customer confirmed the transaction")
        )
        return _dedupe(actions)  # R3 is terminal — no further actions needed

    # R4: No reply within 24 hours
    elif customer_reply is None and evidence.no_reply_24h:
        actions.append(
            Action("MONITOR_CARD", "auto", "R4: no customer reply within 24 hours")
        )
        actions.append(
            Action("DECLINE_TRANSACTION", "L1", "R4: decline pending authorizations after no reply")
        )
        if evidence.exposure_usd > 500:
            actions.append(
                Action("ESCALATE_TO_ANALYST", "auto", "R4: exposure exceeds $500 with no customer reply")
            )

    # R5: Card testing (applies regardless of customer reply)
    if pattern == "card_testing" or evidence.card_testing_detected:
        actions.append(
            Action("DECLINE_TRANSACTION", "L1", "R5: card testing sequence detected")
        )
        actions.append(
            Action("STEP_UP_AUTH", "auto", "R5: card testing — require additional authentication")
        )
        if evidence.large_purchase_cleared:
            actions.append(
                Action(
                    "BLOCK_CARD",
                    route_for_exposure(evidence.exposure_usd),
                    "R5: card testing with purchase over $100 already cleared",
                )
            )

    # R6: Shared origin (applies regardless of customer reply)
    if evidence.shared_origin_detected:
        actions.append(
            Action("CREATE_CASE", "auto", f"R6: shared origin detected — {evidence.shared_element_description}")
        )
        actions.append(
            Action("FILE_REPORT", "L2", f"R6: shared origin — {evidence.shared_element_description}")
        )
        actions.append(
            Action("MONITOR_CONNECTED_CARDS", "auto", f"R6: monitor cards sharing {evidence.shared_element_description}")
        )

    # R7: Disputed but legitimate recurring charge
    if evidence.is_recurring_disputed_but_matches_pattern:
        actions = [
            Action("CREATE_CASE", "auto", "R7: disputed charge matches recurring pattern"),
            Action("VERIFY_WITH_CUSTOMER", "auto", "R7: verify recurring charge dispute"),
            Action("WARN_CUSTOMER", "auto", "R7: warn about recurring charge pattern"),
        ]
        return _dedupe(actions)

    # R8: Escalate when uncertain and exposed
    if evidence.verdict_uncertain and evidence.exposure_usd > 500:
        actions.append(
            Action("ESCALATE_TO_ANALYST", "auto", "R8: uncertain verdict with exposure exceeding $500")
        )
    if evidence.evidence_conflicts and evidence.exposure_usd > 500:
        actions.append(
            Action("ESCALATE_TO_ANALYST", "auto", "R8: conflicting evidence with exposure exceeding $500")
        )

    # R9: Undocumented patterns with coordinated abuse
    if pattern == "undocumented" and evidence.coordinated_abuse:
        actions.append(
            Action("CREATE_CASE", "auto", "R9: undocumented pattern with coordinated abuse")
        )
        actions.append(
            Action("FILE_REPORT", "L2", "R9: undocumented coordinated activity requires filing")
        )
        actions.append(
            Action("ESCALATE_TO_ANALYST", "auto", "R9: undocumented pattern needs analyst review")
        )

    # R10: BLOCK_ALL_CARDS — only if 2+ cards confirmed fraud or credentials compromised
    if evidence.n_cards_with_confirmed_fraud >= 2 or evidence.credentials_compromised:
        actions.append(
            Action("BLOCK_ALL_CARDS", "L2", "R10: multiple cards compromised or credentials confirmed compromised")
        )

    # Fallback: if no actions triggered after final assessment
    if not actions:
        if probability <= 0.15 and evidence.n_evidence_sources >= 2:
            actions.append(
                Action("ALLOW_TRANSACTION", "auto", "Low fraud probability with multiple evidence sources")
            )
            actions.append(
                Action("CLOSE_NO_FRAUD", "auto", "No fraud indicators found after full investigation")
            )
        elif probability >= 0.70:
            actions.append(
                Action("CREATE_CASE", "auto", "High fraud probability after full investigation")
            )
            actions.append(
                Action(
                    "BLOCK_CARD",
                    route_for_exposure(evidence.exposure_usd),
                    "High fraud probability warrants card block",
                )
            )
        else:
            actions.append(
                Action("MONITOR_CARD", "auto", "Moderate risk after investigation — continue monitoring")
            )

    return _dedupe(actions)


def sar_decision(
    verdict: str,
    pattern: str,
    exposure_usd: float,
    shared_origin: bool,
) -> Tuple[bool, str]:
    """
    Determine whether a Suspicious Activity Report should be filed.

    Per Section 3a of the Fraud Policy:
    - File when fraud is confirmed or strongly suspected AND at least one of:
      - Exposure exceeds $1,000
      - Activity connects to a shared device/region/customer fraud
      - Pattern is coordinated or undocumented (R9)

    Returns:
        (should_file, reason_string)
    """
    if verdict != "fraud":
        return (
            False,
            "No confirmed or strongly suspected fraud — no filing required (Section 3a).",
        )

    reasons = []
    if exposure_usd > 1000:
        reasons.append(f"exposure ${exposure_usd:,.2f} exceeds $1,000")
    if shared_origin:
        reasons.append("shared device/region links to other cards' fraud")
    if pattern == "undocumented":
        reasons.append("undocumented coordinated activity (R9)")

    if reasons:
        reason_text = "; ".join(reasons)
        return (
            True,
            f"Section 3a: confirmed fraud with {reason_text}.",
        )

    return (
        False,
        "Confirmed fraud but below filing thresholds: exposure ≤$1,000, "
        "no shared-origin link, documented pattern (Section 3a).",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dedupe(actions: List[Action]) -> List[Action]:
    """Remove duplicate actions, preserving order."""
    seen: set = set()
    result: List[Action] = []
    for a in actions:
        key = a.action  # Dedupe by action name only (keep first occurrence)
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result
