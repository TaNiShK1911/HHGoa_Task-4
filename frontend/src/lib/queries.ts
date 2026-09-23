import { queryOptions } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { AnswerFile, CaseListRow } from "@/types/answerFile";

/**
 * Case feed data. Reads Supabase directly when configured (cases + case_pack),
 * otherwise falls back to the backend's /api/cases summary endpoint.
 */
async function fetchCaseRows(): Promise<CaseListRow[]> {
  if (supabase) {
    const [casesRes, packRes] = await Promise.all([
      supabase
        .from("cases")
        .select(
          "case_id,status,verdict,fraud_probability,pattern,exposure_usd,summary,payload,updated_at",
        ),
      supabase
        .from("case_pack")
        .select(
          "case_id,opened_at,trigger_type,trigger_text,flagged_txn_id,card_id,customer_id,risk_score",
        ),
    ]);
    if (casesRes.error) throw new Error(casesRes.error.message);
    if (packRes.error) throw new Error(packRes.error.message);

    const packById = new Map(
      (packRes.data ?? []).map((row) => [String((row as { case_id: string }).case_id), row]),
    );
    const rows = (casesRes.data ?? []).map((row) => {
      const c = row as Record<string, unknown>;
      const pack = (packById.get(String(c["case_id"])) ?? {}) as Record<string, unknown>;
      return {
        ...c,
        opened_at: (pack["opened_at"] as string) ?? null,
        trigger_type: (pack["trigger_type"] as CaseListRow["trigger_type"]) ?? null,
        trigger_text: (pack["trigger_text"] as string) ?? null,
        flagged_txn_id: (pack["flagged_txn_id"] as string) ?? null,
        card_id: (pack["card_id"] as string) ?? null,
        customer_id: (pack["customer_id"] as string) ?? null,
        risk_score: (pack["risk_score"] as number) ?? null,
      } as CaseListRow;
    });

    // Include trigger records that have no investigation result yet.
    for (const [caseId, pack] of packById) {
      if (rows.some((r) => r.case_id === caseId)) continue;
      const p = pack as Record<string, unknown>;
      rows.push({
        case_id: caseId,
        status: null,
        verdict: null,
        fraud_probability: null,
        pattern: null,
        exposure_usd: null,
        summary: null,
        payload: null,
        updated_at: null,
        opened_at: (p["opened_at"] as string) ?? null,
        trigger_type: (p["trigger_type"] as CaseListRow["trigger_type"]) ?? null,
        trigger_text: (p["trigger_text"] as string) ?? null,
        flagged_txn_id: (p["flagged_txn_id"] as string) ?? null,
        card_id: (p["card_id"] as string) ?? null,
        customer_id: (p["customer_id"] as string) ?? null,
        risk_score: (p["risk_score"] as number) ?? null,
      });
    }

    return rows.sort((a, b) => a.case_id.localeCompare(b.case_id));
  }

  const list = await api.listCases();
  return list.sort((a, b) => a.case_id.localeCompare(b.case_id));
}

async function fetchCase(caseId: string): Promise<AnswerFile> {
  if (supabase) {
    const { data, error } = await supabase
      .from("cases")
      .select("payload")
      .eq("case_id", caseId)
      .maybeSingle();
    if (error) throw new Error(error.message);
    let payload = (data as any)?.payload;
    if (typeof payload === "string") {
      try {
        payload = JSON.parse(payload);
      } catch (e) {
        // ignore
      }
    }
    if (payload) return payload as AnswerFile;
  }
  return api.getCase(caseId);
}

export const casesQuery = () =>
  queryOptions({ queryKey: ["cases"], queryFn: fetchCaseRows, retry: 1, staleTime: 30_000 });

export const caseQuery = (caseId: string) =>
  queryOptions({
    queryKey: ["case", caseId],
    queryFn: () => fetchCase(caseId),
    retry: 1,
    staleTime: 30_000,
  });

export const traceQuery = (caseId: string) =>
  queryOptions({
    queryKey: ["trace", caseId],
    queryFn: () => api.getTrace(caseId),
    retry: 1,
    staleTime: 30_000,
  });

export const neighborhoodQuery = (caseId: string) =>
  queryOptions({
    queryKey: ["neighborhood", caseId],
    queryFn: () => api.getNeighborhood(caseId),
    retry: 1,
    staleTime: 30_000,
  });

export const healthQuery = () =>
  queryOptions({
    queryKey: ["health"],
    queryFn: () => api.health(),
    refetchInterval: 30_000,
    retry: 0,
    staleTime: 0,
  });
