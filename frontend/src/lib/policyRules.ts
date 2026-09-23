/**
 * Static reference copy of the fraud policy R1–R10 used only to render citation
 * dialogs. No rule evaluation happens in this frontend — the backend policy
 * engine owns every action/route decision.
 */
export interface PolicyRule {
  id: string;
  title: string;
  text: string;
}

export const POLICY_RULES: Record<string, PolicyRule> = {
  R1: {
    id: "R1",
    title: "Confirmed fraud — card containment",
    text: "When a transaction is confirmed fraudulent, block the card immediately and mark all linked transactions for review.",
  },
  R2: {
    id: "R2",
    title: "Card testing pattern",
    text: "Multiple low-value authorisations on one card within a short window indicate card testing. Freeze the card and monitor for a follow-on high-value attempt.",
  },
  R3: {
    id: "R3",
    title: "Card-not-present with a new device",
    text: "Card-not-present activity from a device profile never seen for the customer requires step-up authentication before the transaction is released.",
  },
  R4: {
    id: "R4",
    title: "Out-of-region use",
    text: "A transaction billed outside the customer's established region is suspicious unless corroborated by travel evidence or prior activity in that region.",
  },
  R5: {
    id: "R5",
    title: "Shared device across cards",
    text: "A device profile linked to cards belonging to multiple customers indicates an organised ring; escalate and review every connected card.",
  },
  R6: {
    id: "R6",
    title: "Account takeover signals",
    text: "Credential or contact-detail changes shortly before high-risk spending indicate account takeover. Suspend the session, force re-authentication and review recent changes.",
  },
  R7: {
    id: "R7",
    title: "Customer validation before closure",
    text: "A case may not be closed as legitimate on a single signal. Request customer validation and record the response as evidence first.",
  },
  R8: {
    id: "R8",
    title: "Approval routing by exposure",
    text: "Exposure under $500 may be actioned automatically. $500–$5,000 requires L1 analyst approval. Above $5,000 requires L2 approval.",
  },
  R9: {
    id: "R9",
    title: "SAR filing threshold",
    text: "File a Suspicious Activity Report when confirmed fraudulent activity totals $5,000 or more, or when the activity spans multiple customers or accounts.",
  },
  R10: {
    id: "R10",
    title: "Stopping condition",
    text: "Stop investigating once the verdict is supported by sufficient evidence, or once further evidence gathering cannot change the recommended action.",
  },
};

export function lookupRule(raw: string): PolicyRule | null {
  const match = raw.toUpperCase().match(/R(\d{1,2})/);
  if (!match) return null;
  return POLICY_RULES[`R${Number(match[1])}`] ?? null;
}
