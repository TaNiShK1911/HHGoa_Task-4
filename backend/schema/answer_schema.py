"""
Pydantic v2 model for the Answer Format — Section 8 of the implementation plan.

Every emitted case must pass AnswerFile.model_validate() before being written
to disk or to the graph. Field names, types, and enum values match the README
verbatim.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ── Enums (exact values from the README) ──────────────────────────────────────

class CaseStatus(str, Enum):
    OPEN = "open"
    CLOSED_FRAUD = "closed_fraud"
    CLOSED_LEGITIMATE = "closed_legitimate"
    ESCALATED = "escalated"


class Verdict(str, Enum):
    FRAUD = "fraud"
    LEGITIMATE = "legitimate"
    UNCERTAIN = "uncertain"


class Pattern(str, Enum):
    CARD_TESTING = "card_testing"
    CARD_NOT_PRESENT_FRAUD = "card_not_present_fraud"
    CARD_NOT_PRESENT_NEW_DEVICE = "card_not_present_new_device"
    OUT_OF_REGION_USE = "out_of_region_use"
    ACCOUNT_TAKEOVER = "account_takeover"
    UNDOCUMENTED = "undocumented"
    NONE = "none"


class ActionName(str, Enum):
    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class Route(str, Enum):
    AUTO = "auto"
    L1 = "L1"
    L2 = "L2"


class EvidenceRequestType(str, Enum):
    CUSTOMER_VALIDATION = "customer_validation"
    STEP_UP_AUTH = "step_up_auth"
    ANALYST_INFO = "analyst_info"


class EvidenceSource(str, Enum):
    GRAPH = "graph"
    DOCUMENT = "document"
    CUSTOMER = "customer"
    EXTERNAL = "external"


# ── Sub-models ────────────────────────────────────────────────────────────────

class Evidence(BaseModel):
    """A single piece of evidence supporting the investigation."""
    claim: str
    source: EvidenceSource
    ref: str
    entity_ids: List[str] = Field(default_factory=list)


class EvidenceRequest(BaseModel):
    """A request for additional evidence made during the investigation."""
    type: EvidenceRequestType
    asked_after_step: int
    assumed_response: str


class ActionRecommendation(BaseModel):
    """A single recommended action with approval route and policy citation."""
    action: ActionName
    route: Route
    reason: str


class CaseDetail(BaseModel):
    """Part 1: The bank's internal investigation record (15 fields)."""
    status: CaseStatus
    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: Pattern
    pattern_description: str = ""
    affected_txn_ids: List[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: List[str] = Field(default_factory=list)
    connected_device_profiles: List[str] = Field(default_factory=list)
    exposure_usd: float = 0.0
    evidence: List[Evidence] = Field(default_factory=list)
    similar_prior_cases: List[str] = Field(default_factory=list)
    summary: str = ""
    written_to_graph: bool = False
    graph_case_id: str = ""

    @model_validator(mode="after")
    def validate_pattern_description(self) -> "CaseDetail":
        """pattern_description must be non-empty iff pattern is 'undocumented'."""
        if self.pattern == Pattern.UNDOCUMENTED and not self.pattern_description.strip():
            raise ValueError(
                "pattern_description is required when pattern is 'undocumented'"
            )
        if self.pattern != Pattern.UNDOCUMENTED and self.pattern_description.strip():
            raise ValueError(
                "pattern_description must be empty when pattern is not 'undocumented'"
            )
        return self

    @model_validator(mode="after")
    def validate_legitimate_verdict(self) -> "CaseDetail":
        """Legitimate verdicts must have empty affected_txn_ids, zero exposure, no SAR."""
        if self.verdict == Verdict.LEGITIMATE:
            if self.affected_txn_ids:
                raise ValueError(
                    "legitimate verdict must have empty affected_txn_ids"
                )
            if self.exposure_usd != 0.0:
                raise ValueError(
                    "legitimate verdict must have zero exposure_usd"
                )
        return self


class SARReport(BaseModel):
    """Part 2: Suspicious Activity Report (6 fields)."""
    file: bool
    reason: str
    narrative: str = ""
    subjects: List[str] = Field(default_factory=list)
    total_amount_usd: float = 0.0
    activity_dates: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sar_consistency(self) -> "SARReport":
        """When file is false, narrative/subjects/amount/dates must be empty/zero."""
        if not self.file:
            if self.narrative:
                raise ValueError("narrative must be empty when file is false")
            if self.subjects:
                raise ValueError("subjects must be empty when file is false")
            if self.total_amount_usd != 0.0:
                raise ValueError(
                    "total_amount_usd must be 0 when file is false"
                )
            if self.activity_dates:
                raise ValueError(
                    "activity_dates must be empty when file is false"
                )
        else:
            if not self.narrative.strip():
                raise ValueError("narrative is required when file is true")
            if len(self.activity_dates) != 2:
                raise ValueError(
                    "activity_dates must have exactly 2 entries when file is true"
                )
        return self


class NextBestActions(BaseModel):
    """Part 3: Next best actions — initial, final, and what changed (3 fields)."""
    initial: List[ActionRecommendation]
    final: List[ActionRecommendation]
    what_changed: str


# ── Top-level Answer File ─────────────────────────────────────────────────────

class AnswerFile(BaseModel):
    """
    Complete answer file for one case.

    Submit one JSON file per case, named <case_id>.json.
    Each answer has three parts: case, SAR, and next best actions.
    """
    case_id: str
    case: CaseDetail
    evidence_requests: List[EvidenceRequest] = Field(default_factory=list)
    next_best_actions: NextBestActions
    sar: SARReport
    stop_reason: str
    tool_calls: int = 0
    tokens: int = 0
    latency_s: float = 0.0

    @model_validator(mode="after")
    def validate_sar_file_report_agreement(self) -> "AnswerFile":
        """sar.file must agree with whether FILE_REPORT appears in final actions."""
        has_file_report = any(
            a.action == ActionName.FILE_REPORT
            for a in self.next_best_actions.final
        )
        if self.sar.file and not has_file_report:
            raise ValueError(
                "sar.file is true but FILE_REPORT not in next_best_actions.final"
            )
        if not self.sar.file and has_file_report:
            raise ValueError(
                "FILE_REPORT in next_best_actions.final but sar.file is false"
            )
        return self

    @model_validator(mode="after")
    def validate_legitimate_sar(self) -> "AnswerFile":
        """Legitimate verdicts must have sar.file == false."""
        if self.case.verdict == Verdict.LEGITIMATE and self.sar.file:
            raise ValueError(
                "legitimate verdict must have sar.file == false"
            )
        return self
