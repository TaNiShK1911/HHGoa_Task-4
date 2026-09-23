import type { AnswerFile, CaseListRow, Neighborhood, TraceStep } from "@/types/answerFile";

export const API_BASE_URL = (
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? ""
).replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE_URL) {
    throw new ApiError(
      "Investigation service URL is not configured (VITE_API_BASE_URL).",
      0,
    );
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Could not reach the investigation service.", 0);
  }
  if (!res.ok) {
    throw new ApiError(`Investigation service returned ${res.status}.`, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  listCases: () => request<CaseListRow[]>("/api/cases"),
  getCase: (caseId: string) => request<AnswerFile>(`/api/cases/${encodeURIComponent(caseId)}`),
  getTrace: (caseId: string) =>
    request<TraceStep[]>(`/api/cases/${encodeURIComponent(caseId)}/trace`),
  getNeighborhood: (caseId: string) =>
    request<Neighborhood>(`/api/cases/${encodeURIComponent(caseId)}/neighborhood`),
  runCase: (caseId: string) =>
    request<AnswerFile>(`/api/cases/${encodeURIComponent(caseId)}/run`, { method: "POST" }),
  health: () => request<{ status: string }>("/api/health"),
};
