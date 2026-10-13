"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, streamUrl } from "./api";
import type { LeadDetail, LeadOut, RunCounts, RunOut, RunStatus } from "./types";

export interface LeadWarning {
  company: string | null;
  lead_id?: string;
  reason: string;
  upstream?: boolean;
}

export interface RunState {
  run: RunOut | null;
  leads: Map<string, LeadOut>;
  arrival: string[]; // lead ids in the order they streamed in
  status: RunStatus | "connecting";
  counts: RunCounts;
  mode: string | null;
  warnings: LeadWarning[];
  error: string | null;
  done: boolean;
  startedAt: number;
  finishedMs: number | null;
  resumes: number;
  details: Map<string, LeadDetail>; // static demo ships details inline
  fresh: Set<string>; // ids that arrived in the latest batch (rows fade in once)
}

const initial = (): RunState => ({
  run: null,
  leads: new Map(),
  arrival: [],
  status: "connecting",
  counts: {},
  mode: null,
  warnings: [],
  error: null,
  done: false,
  startedAt: Date.now(),
  finishedMs: null,
  resumes: 0,
  details: new Map(),
  fresh: new Set(),
});

/**
 * Opens the run's SSE stream (which *is* the run on the server). Handles:
 * `status`, `lead` (upsert), `warning`, `resume` (reconnect: the server resumes unscored companies),
 * `done`/`error` (close — EventSource would otherwise auto-reconnect and replay forever).
 */
export function useRun(runId: string): RunState {
  const [state, setState] = useState<RunState>(initial);
  const esRef = useRef<EventSource | null>(null);
  const pending = useRef<LeadOut[]>([]);
  const flushTimer = useRef<number | null>(null);

  // Batch lead events into one render every ~60 ms (a replay delivers hundreds at once).
  const flush = useCallback(() => {
    flushTimer.current = null;
    const batch = pending.current;
    pending.current = [];
    if (!batch.length) return;
    setState((s) => {
      const leads = new Map(s.leads);
      const arrival = [...s.arrival];
      const fresh = new Set<string>();
      for (const l of batch) {
        if (!leads.has(l.id)) {
          arrival.push(l.id);
          fresh.add(l.id);
        }
        leads.set(l.id, l);
      }
      return { ...s, leads, arrival, fresh };
    });
  }, []);

  useEffect(() => {
    if (runId === "demo") {
      let cancelled = false;
      fetch("/demo/run.json")
        .then((r) => r.json())
        .then((data: { run: RunOut; leads: LeadDetail[] }) => {
          if (cancelled) return;
          const leads = new Map<string, LeadOut>();
          const details = new Map<string, LeadDetail>();
          for (const l of data.leads) {
            leads.set(l.id, l);
            details.set(l.id, l);
          }
          setState({
            ...initial(),
            run: data.run,
            leads,
            details,
            arrival: data.leads.map((l) => l.id),
            status: "done",
            counts: data.run.counts,
            mode: data.run.mode,
            warnings: data.run.warnings ?? [],
            done: true,
            finishedMs: durationMs(data.run),
          });
        })
        .catch(() => !cancelled && setState((s) => ({ ...s, error: "The demo run couldn't be loaded." })));
      return () => {
        cancelled = true;
      };
    }

    let closed = false;
    api
      .run(runId)
      .then((run) => !closed && setState((s) => ({ ...s, run, mode: run.mode, counts: { ...run.counts, ...s.counts } })))
      .catch((e: ApiError) => !closed && setState((s) => ({ ...s, error: e.status === 404 ? "This run doesn't exist." : e.message })));

    const open = () => {
      if (closed) return;
      const es = new EventSource(streamUrl(runId));
      esRef.current = es;
      es.addEventListener("status", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        setState((s) => ({ ...s, status: d.status, counts: d.counts ?? s.counts, mode: d.mode ?? s.mode }));
      });
      es.addEventListener("lead", (ev) => {
        pending.current.push(JSON.parse((ev as MessageEvent).data));
        // A timer, not requestAnimationFrame: rAF is paused in background tabs, and runs take minutes.
        if (flushTimer.current === null) flushTimer.current = window.setTimeout(flush, 60);
      });
      es.addEventListener("warning", (ev) => {
        const w = JSON.parse((ev as MessageEvent).data) as LeadWarning;
        setState((s) =>
          s.warnings.some((x) => x.reason === w.reason && x.company === w.company)
            ? s
            : { ...s, warnings: [...s.warnings, w] },
        );
      });
      es.addEventListener("resume", () => {
        // The server hit its time budget; reopening continues with unscored companies.
        es.close();
        setState((s) => ({ ...s, resumes: s.resumes + 1 }));
        window.setTimeout(open, 400);
      });
      es.addEventListener("done", (ev) => {
        const d = JSON.parse((ev as MessageEvent).data);
        es.close();
        flush();
        setState((s) => ({
          ...s,
          status: "done",
          done: true,
          counts: d.counts ?? s.counts,
          finishedMs: d.duration_ms ?? Date.now() - s.startedAt,
        }));
      });
      es.addEventListener("error", (ev) => {
        const data = (ev as MessageEvent).data;
        if (data) {
          // Server-sent `error` event: the run failed.
          es.close();
          const d = JSON.parse(data);
          setState((s) => ({ ...s, status: "failed", error: d.message ?? "Run failed", done: true }));
        } else if (es.readyState === EventSource.CLOSED) {
          setState((s) => (s.done ? s : { ...s, error: "Lost connection to the run. Reload to resume." }));
        }
        // readyState CONNECTING: the browser is retrying a dropped connection by itself.
      });
    };
    open();
    return () => {
      closed = true;
      esRef.current?.close();
      if (flushTimer.current !== null) window.clearTimeout(flushTimer.current);
    };
  }, [runId, flush]);

  return state;
}

function durationMs(run: RunOut): number | null {
  if (!run.started_at || !run.finished_at) return null;
  return new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
}
