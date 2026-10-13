import type { Health, LeadDetail, LeadOut, Preset, RunOut, ThesisIn, Weights } from "./types";

/** Same-origin in production (Vercel routes /api/* to FastAPI) and in dev (next.config rewrite). */
export const API = "/api/v1";

/**
 * SSE goes straight to the API in dev: the Next dev proxy can buffer streamed responses.
 * In production the stream is same-origin (Vercel Services), so this is empty.
 */
export const STREAM_ORIGIN = process.env.NEXT_PUBLIC_STREAM_ORIGIN ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    public title: string,
    public detail?: string,
    public body?: Record<string, unknown>,
  ) {
    super(detail || title);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the API", "Check your connection and try again.");
  }
  if (!res.ok) {
    let body: Record<string, unknown> = {};
    try {
      body = await res.json();
    } catch {
      /* not problem+json */
    }
    throw new ApiError(
      res.status,
      String(body.title ?? res.statusText ?? "Request failed"),
      body.detail ? String(body.detail) : undefined,
      body,
    );
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/healthz"),

  createRun: (body: ThesisIn) =>
    request<{ run_id: string; stream_url: string }>("/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  createCsvRun: (file: File, preset: Preset) => {
    const fd = new FormData();
    fd.set("file", file);
    fd.set("preset", preset);
    return request<{
      run_id: string;
      stream_url: string;
      rows_accepted: number;
      rows_rejected: number;
      mapping: Record<string, string>;
    }>("/runs/csv", { method: "POST", body: fd });
  },

  createDemoRun: () => request<{ run_id: string; stream_url: string }>("/runs/demo", { method: "POST" }),

  run: (id: string) => request<RunOut>(`/runs/${id}`),

  lead: (id: string, w: Weights) =>
    request<LeadDetail>(`/leads/${id}?wd=${w.durability}&ws=${w.succession}&wu=${w.upside}`),

  leads: (runId: string, page = 1) =>
    request<{ items: LeadOut[]; total: number }>(`/runs/${runId}/leads?page=${page}&page_size=100`),

  feedback: (id: string, vote: 1 | -1) =>
    request<void>(`/leads/${id}/feedback`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ vote }),
    }),

  exportCsv: async (leadIds: string[], w: Weights): Promise<Blob> => {
    const res = await fetch(`${API}/export/csv`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ lead_ids: leadIds, weights: w }),
    });
    if (!res.ok) throw new ApiError(res.status, "Export failed");
    return res.blob();
  },

  exportHubspot: (leadIds: string[], w: Weights) =>
    request<{ created: number; updated: number; failed: { domain: string | null; reason: string }[] }>(
      "/export/hubspot",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ lead_ids: leadIds, weights: w }),
      },
    ),
};

export function streamUrl(runId: string): string {
  return `${STREAM_ORIGIN}${API}/runs/${runId}/stream`;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
