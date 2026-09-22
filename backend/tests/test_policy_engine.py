"""
Unit tests for the Deterministic Policy Engine — one dedicated test per rule R1–R10.

Each test constructs a minimal EvidenceBundle fixture that triggers exactly
that rule and asserts the exact action list and approval route.

Run: pytest tests/test_policy_engine.py -v
"""

import sys
import os

# Ensure the backend directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from agent.policy_engine import (
    Action,
    EvidenceBundle,
    decide_initial,
    decide_final,
    route_for_exposure,
    sar_decision,
)


# ── R1: Verify before blocking on a weak signal ─────────────────────────────

class TestR1:
    """
    R1: If case rests on single signal AND probability < 0.70,
    recommend VERIFY_WITH_CUSTOMER before any block.
    """

    def test_single_signal_low_probability_triggers_verify(self):
        evidence = EvidenceBundle(
            is_single_signal=True,
            n_evidence_sources=1,
            fraud_probability=0.55,
            exposure_usd=200,
        )
        actions = decide_initial(evidence, probability=0.55, pattern="none")
        action_names = [a.action for a in actions]
        assert "VERIFY_WITH_CUSTOMER" in action_names
        # Should NOT have BLOCK_CARD when only single signal below 0.70
        assert "BLOCK_CARD" not in action_names

    def test_single_signal_high_probability_no_verify_needed(self):
        """Above 0.70 probability, R1 does not force verification."""
        evidence = EvidenceBundle(
            is_single_signal=True,
            n_evidence_sources=1,
            fraud_probability=0.75,
            exposure_usd=200,
        )
        actions = decide_initial(evidence, probability=0.75, pattern="none")
        action_names = [a.action for a in actions]
        # R1 should not fire — probability is above 0.70
        r1_actions = [a for a in actions if "R1" in a.reason]
        assert len(r1_actions) == 0

    def test_multiple_signals_low_probability_no_r1(self):
        """R1 only applies when it's a single signal."""
        evidence = EvidenceBundle(
            is_single_signal=False,
            n_evidence_sources=3,
            fraud_probability=0.55,
            exposure_usd=200,
        )
        actions = decide_initial(evidence, probability=0.55, pattern="none")
        r1_actions = [a for a in actions if "R1" in a.reason]
        assert len(r1_actions) == 0


# ── R2: Customer denies the transaction ──────────────────────────────────────

class TestR2:
    """
    R2: Customer denies → BLOCK_CARD + CREATE_CASE.
    Add FILE_REPORT if exposure > $1,000 or shared origin.
    """

    def test_customer_denial_basic(self):
        evidence = EvidenceBundle(
            customer_reply="denied",
            exposure_usd=500,
            shared_origin_detected=False,
        )
        actions = decide_final(
            evidence, probability=0.80, pattern="card_not_present_fraud",
            customer_reply="denied",
        )
        action_names = [a.action for a in actions]
        assert "BLOCK_CARD" in action_names
        assert "CREATE_CASE" in action_names
        # Exposure <= $1,000 and no shared origin → no FILE_REPORT from R2
        r2_file_actions = [a for a in actions if a.action == "FILE_REPORT" and "R2" in a.reason]
        assert len(r2_file_actions) == 0

    def test_customer_denial_high_exposure(self):
        """Exposure > $1,000 → FILE_REPORT added."""
        evidence = EvidenceBundle(
            customer_reply="denied",
            exposure_usd=2000,
            shared_origin_detected=False,
        )
        actions = decide_final(
            evidence, probability=0.85, pattern="card_not_present_fraud",
            customer_reply="denied",
        )
        action_names = [a.action for a in actions]
        assert "BLOCK_CARD" in action_names
        assert "CREATE_CASE" in action_names
        assert "FILE_REPORT" in action_names

    def test_customer_denial_shared_origin(self):
        """Shared origin → FILE_REPORT added even with low exposure."""
        evidence = EvidenceBundle(
            customer_reply="denied",
            exposure_usd=300,
            shared_origin_detected=True,
            shared_element_description="device profile D000731",
        )
        actions = decide_final(
            evidence, probability=0.80, pattern="card_not_present_fraud",
            customer_reply="denied",
        )
        action_names = [a.action for a in actions]
        assert "FILE_REPORT" in action_names

    def test_customer_denial_block_card_route(self):
        """BLOCK_CARD route depends on exposure: ≤$2,500 → L1, >$2,500 → L2."""
        # Low exposure → L1
        evidence_low = EvidenceBundle(customer_reply="denied", exposure_usd=1000)
        actions_low = decide_final(evidence_low, 0.80, "card_not_present_fraud", "denied")
        block_low = [a for a in actions_low if a.action == "BLOCK_CARD"][0]
        assert block_low.route == "L1"

        # High exposure → L2
        evidence_high = EvidenceBundle(customer_reply="denied", exposure_usd=5000)
        actions_high = decide_final(evidence_high, 0.80, "card_not_present_fraud", "denied")
        block_high = [a for a in actions_high if a.action == "BLOCK_CARD"][0]
        assert block_high.route == "L2"


# ── R3: Customer confirms the transaction ────────────────────────────────────

class TestR3:
    """R3: Customer confirms → CLOSE_NO_FRAUD. Terminal action."""

    def test_customer_confirms(self):
        evidence = EvidenceBundle(customer_reply="confirmed", exposure_usd=500)
        actions = decide_final(
            evidence, probability=0.40, pattern="none",
            customer_reply="confirmed",
        )
        assert len(actions) == 1
        assert actions[0].action == "CLOSE_NO_FRAUD"
        assert actions[0].route == "auto"
        assert "R3" in actions[0].reason


# ── R4: No reply within 24 hours ────────────────────────────────────────────

class TestR4:
    """
    R4: No reply 24h → MONITOR_CARD + DECLINE_TRANSACTION.
    Escalate if exposure > $500.
    """

    def test_no_reply_basic(self):
        evidence = EvidenceBundle(
            customer_reply=None,
            no_reply_24h=True,
            exposure_usd=200,
        )
        actions = decide_final(
            evidence, probability=0.55, pattern="none",
            customer_reply=None,
        )
        action_names = [a.action for a in actions]
        assert "MONITOR_CARD" in action_names
        assert "DECLINE_TRANSACTION" in action_names
        # Exposure ≤ $500 → no escalation
        assert "ESCALATE_TO_ANALYST" not in action_names

    def test_no_reply_high_exposure(self):
        """Exposure > $500 → ESCALATE_TO_ANALYST added."""
        evidence = EvidenceBundle(
            customer_reply=None,
            no_reply_24h=True,
            exposure_usd=800,
        )
        actions = decide_final(
            evidence, probability=0.55, pattern="none",
            customer_reply=None,
        )
        action_names = [a.action for a in actions]
        assert "MONITOR_CARD" in action_names
        assert "DECLINE_TRANSACTION" in action_names
        assert "ESCALATE_TO_ANALYST" in action_names


# ── R5: Card testing ────────────────────────────────────────────────────────

class TestR5:
    """
    R5: Card testing (3+ small online in 1h + larger purchase):
    DECLINE_TRANSACTION + STEP_UP_AUTH.
    If purchase > $100 already cleared → BLOCK_CARD.
    """

    def test_card_testing_basic(self):
        evidence = EvidenceBundle(
            card_testing_detected=True,
            large_purchase_cleared=False,
            exposure_usd=15,
        )
        actions = decide_initial(evidence, probability=0.75, pattern="card_testing")
        action_names = [a.action for a in actions]
        assert "DECLINE_TRANSACTION" in action_names
        assert "STEP_UP_AUTH" in action_names
        assert "BLOCK_CARD" not in action_names

    def test_card_testing_large_purchase_cleared(self):
        """Purchase > $100 cleared → add BLOCK_CARD."""
        evidence = EvidenceBundle(
            card_testing_detected=True,
            large_purchase_cleared=True,
            exposure_usd=268,
        )
        actions = decide_initial(evidence, probability=0.75, pattern="card_testing")
        action_names = [a.action for a in actions]
        assert "DECLINE_TRANSACTION" in action_names
        assert "STEP_UP_AUTH" in action_names
        assert "BLOCK_CARD" in action_names
        # Exposure $268 ≤ $2,500 → route is L1
        block = [a for a in actions if a.action == "BLOCK_CARD"][0]
        assert block.route == "L1"


# ── R6: Shared origin ───────────────────────────────────────────────────────

class TestR6:
    """
    R6: Shared device/region/email across cards:
    CREATE_CASE + FILE_REPORT + MONITOR_CONNECTED_CARDS.
    """

    def test_shared_origin(self):
        evidence = EvidenceBundle(
            shared_origin_detected=True,
            shared_element_description="device profile D000731",
            exposure_usd=500,
        )
        actions = decide_initial(evidence, probability=0.70, pattern="card_not_present_fraud")
        action_names = [a.action for a in actions]
        assert "CREATE_CASE" in action_names
        assert "FILE_REPORT" in action_names
        assert "MONITOR_CONNECTED_CARDS" in action_names
        # FILE_REPORT always L2
        file_report = [a for a in actions if a.action == "FILE_REPORT"][0]
        assert file_report.route == "L2"


# ── R7: Disputed but legitimate ─────────────────────────────────────────────

class TestR7:
    """
    R7: Disputed charge matching recurring pattern:
    CREATE_CASE + VERIFY_WITH_CUSTOMER + WARN_CUSTOMER. No blocking.
    """

    def test_disputed_recurring(self):
        evidence = EvidenceBundle(
            is_recurring_disputed_but_matches_pattern=True,
            exposure_usd=100,
        )
        actions = decide_initial(evidence, probability=0.30, pattern="none")
        action_names = [a.action for a in actions]
        assert "CREATE_CASE" in action_names
        assert "VERIFY_WITH_CUSTOMER" in action_names
        assert "WARN_CUSTOMER" in action_names
        # Must NOT block
        assert "BLOCK_CARD" not in action_names
        assert "BLOCK_ALL_CARDS" not in action_names
        assert "DECLINE_TRANSACTION" not in action_names


# ── R8: Escalate when uncertain and exposed ──────────────────────────────────

class TestR8:
    """
    R8: Uncertain verdict AND exposure > $500 → ESCALATE_TO_ANALYST.
    Also applies when evidence conflicts.
    """

    def test_uncertain_high_exposure(self):
        evidence = EvidenceBundle(
            verdict_uncertain=True,
            exposure_usd=800,
        )
        actions = decide_initial(evidence, probability=0.50, pattern="none")
        action_names = [a.action for a in actions]
        assert "ESCALATE_TO_ANALYST" in action_names

    def test_uncertain_low_exposure_no_escalation(self):
        """Exposure ≤ $500 → R8 does not trigger."""
        evidence = EvidenceBundle(
            verdict_uncertain=True,
            exposure_usd=300,
        )
        actions = decide_initial(evidence, probability=0.50, pattern="none")
        r8_actions = [a for a in actions if "R8" in a.reason]
        assert len(r8_actions) == 0

    def test_conflicting_evidence_high_exposure(self):
        evidence = EvidenceBundle(
            evidence_conflicts=True,
            exposure_usd=1000,
        )
        actions = decide_initial(evidence, probability=0.50, pattern="none")
        action_names = [a.action for a in actions]
        assert "ESCALATE_TO_ANALYST" in action_names


# ── R9: Undocumented patterns ────────────────────────────────────────────────

class TestR9:
    """
    R9: Undocumented pattern with coordinated abuse:
    CREATE_CASE + FILE_REPORT + ESCALATE_TO_ANALYST.
    """

    def test_undocumented_coordinated(self):
        evidence = EvidenceBundle(
            coordinated_abuse=True,
            exposure_usd=500,
        )
        actions = decide_initial(evidence, probability=0.70, pattern="undocumented")
        action_names = [a.action for a in actions]
        assert "CREATE_CASE" in action_names
        assert "FILE_REPORT" in action_names
        assert "ESCALATE_TO_ANALYST" in action_names

    def test_undocumented_not_coordinated_no_r9(self):
        """Undocumented pattern without coordinated abuse → R9 does not fire."""
        evidence = EvidenceBundle(
            coordinated_abuse=False,
            exposure_usd=500,
        )
        actions = decide_initial(evidence, probability=0.70, pattern="undocumented")
        r9_actions = [a for a in actions if "R9" in a.reason]
        assert len(r9_actions) == 0


# ── R10: Never BLOCK_ALL_CARDS unless ≥2 cards confirmed or creds compromised ─

class TestR10:
    """
    R10: BLOCK_ALL_CARDS only if ≥2 cards show confirmed fraud
    or credentials confirmed compromised.
    """

    def test_two_cards_compromised(self):
        evidence = EvidenceBundle(
            n_cards_with_confirmed_fraud=2,
            credentials_compromised=False,
            customer_reply="denied",
            exposure_usd=5000,
        )
        actions = decide_final(
            evidence, probability=0.90, pattern="account_takeover",
            customer_reply="denied",
        )
        action_names = [a.action for a in actions]
        assert "BLOCK_ALL_CARDS" in action_names
        block_all = [a for a in actions if a.action == "BLOCK_ALL_CARDS"][0]
        assert block_all.route == "L2"

    def test_credentials_compromised(self):
        evidence = EvidenceBundle(
            n_cards_with_confirmed_fraud=0,
            credentials_compromised=True,
            customer_reply="denied",
            exposure_usd=3000,
        )
        actions = decide_final(
            evidence, probability=0.90, pattern="account_takeover",
            customer_reply="denied",
        )
        action_names = [a.action for a in actions]
        assert "BLOCK_ALL_CARDS" in action_names

    def test_single_card_no_block_all(self):
        """Only 1 card compromised, no credentials → no BLOCK_ALL_CARDS."""
        evidence = EvidenceBundle(
            n_cards_with_confirmed_fraud=1,
            credentials_compromised=False,
            customer_reply="denied",
            exposure_usd=3000,
        )
        actions = decide_final(
            evidence, probability=0.90, pattern="card_not_present_fraud",
            customer_reply="denied",
        )
        action_names = [a.action for a in actions]
        assert "BLOCK_ALL_CARDS" not in action_names


# ── Approval routing tests ───────────────────────────────────────────────────

class TestRouting:
    """Test route_for_exposure threshold at $2,500."""

    def test_below_threshold(self):
        assert route_for_exposure(2500) == "L1"
        assert route_for_exposure(100) == "L1"

    def test_above_threshold(self):
        assert route_for_exposure(2501) == "L2"
        assert route_for_exposure(10000) == "L2"


# ── SAR decision tests ──────────────────────────────────────────────────────

class TestSARDecision:
    """Test sar_decision logic per Section 3a."""

    def test_not_fraud_no_filing(self):
        should_file, reason = sar_decision("legitimate", "none", 500, False)
        assert should_file is False

    def test_fraud_high_exposure(self):
        should_file, reason = sar_decision("fraud", "card_not_present_fraud", 2000, False)
        assert should_file is True
        assert "$1,000" in reason or "1,000" in reason

    def test_fraud_shared_origin(self):
        should_file, reason = sar_decision("fraud", "card_not_present_fraud", 500, True)
        assert should_file is True

    def test_fraud_undocumented(self):
        should_file, reason = sar_decision("fraud", "undocumented", 500, False)
        assert should_file is True

    def test_fraud_below_thresholds(self):
        should_file, reason = sar_decision("fraud", "card_testing", 500, False)
        assert should_file is False
