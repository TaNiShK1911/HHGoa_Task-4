export type CaseStatus = "open" | "closed_fraud" | "closed_legitimate" | "escalated";
export type Verdict = "fraud" | "legitimate" | "uncertain";
export type Pattern =
  | "card_testing"
  | "card_not_present_fraud"
  | "card_not_present_new_device"
  | "out_of_region_use"
  | "account_takeover"
  | "undocumented"
  | "none";
export type ActionRoute = "auto" | "L1" | "L2";
export type EvidenceSource = "graph" | "document" | "customer" | "external";
export type EvidenceRequestType = "customer_validation" | "step_up_auth" | "analyst_info";
export type TriggerType = "risk_score" | "customer_report" | "analyst_request";

export interface EvidenceItem {
  claim: string;
  source: EvidenceSource;
  ref: string;
  entity_ids: string[];
}

export interface NextBestAction {
  action: string;
  route: ActionRoute;
  reason: string;
}

export interface EvidenceRequest {
  type: EvidenceRequestType;
  asked_after_step: number;
  assumed_response: string;
}

export interface AnswerFile {
  case_id: string;
  case: {
    status: CaseStatus;
    verdict: Verdict;
    fraud_probability: number;
    pattern: Pattern;
    pattern_description: string;
    affected_txn_ids: string[];
    first_suspicious_txn_id: string;
    connected_card_ids: string[];
    connected_device_profiles: string[];
    exposure_usd: number;
    evidence: EvidenceItem[];
    similar_prior_cases: string[];
    summary: string;
    written_to_graph: boolean;
    graph_case_id: string;
  };
  evidence_requests: EvidenceRequest[];
  next_best_actions: {
    initial: NextBestAction[];
    final: NextBestAction[];
    what_changed: string;
  };
  sar: {
    file: boolean;
    reason: string;
    narrative: string;
    subjects: string[];
    total_amount_usd: number;
    activity_dates: string[];
  };
  stop_reason: string;
  tool_calls: number;
  tokens: number;
  latency_s: number;
}

export interface TraceStep {
  node_name: string;
  timestamp: string;
  input_summary: string;
  output_summary: string;
  policy_rule_fired?: string;
}

export interface NeighborhoodNode {
  id: string;
  label: string;
  type: string;
  [key: string]: unknown;
}

export interface NeighborhoodEdge {
  source: string;
  target: string;
  label: string;
}

export interface Neighborhood {
  nodes: NeighborhoodNode[];
  edges: NeighborhoodEdge[];
}

/** Row shape used by the case feed: `cases` merged with its `case_pack` trigger record. */
export interface CaseListRow {
  case_id: string;
  status: CaseStatus | null;
  verdict: Verdict | null;
  fraud_probability: number | null;
  pattern: Pattern | null;
  exposure_usd: number | null;
  summary: string | null;
  updated_at: string | null;
  payload: AnswerFile | null;
  opened_at: string | null;
  trigger_type: TriggerType | null;
  trigger_text: string | null;
  flagged_txn_id: string | null;
  card_id: string | null;
  customer_id: string | null;
  risk_score: number | null;
}
