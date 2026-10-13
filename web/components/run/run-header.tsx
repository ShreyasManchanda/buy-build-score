"use client";

import { CheckIcon, ChevronLeftIcon, CircleAlertIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { elapsed, plural, thesisSummary } from "@/lib/format";
import type { RunState } from "@/lib/use-run";
import { cn } from "@/lib/utils";

type Stage = "discovering" | "crawling" | "scoring" | "done";
const ORDER: Stage[] = ["discovering", "crawling", "scoring", "done"];

function stageOf(state: RunState): Stage {
  if (state.done) return "done";
  const s = state.status;
  if (s === "discovering" || s === "queued" || s === "connecting") return "discovering";
  if (s === "scoring") return "scoring";
  return "crawling";
}

export function RunHeader({ state }: { state: RunState }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (state.done) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [state.done]);

  const stage = stageOf(state);
  const total = state.counts.deduped ?? 0;
  const scored = state.leads.size;
  const pct = state.done ? 100 : total ? Math.min(98, Math.round((scored / total) * 100)) : stage === "discovering" ? 4 : 8;
  const ms = state.done ? (state.finishedMs ?? 0) : now - state.startedAt;
  const siteOnly = state.mode !== "places";
  const summary = thesisSummary(state.run) || (state.run ? "" : "Loading run…");

  // Progress in the tab title, so a run working in a background tab is visible from the tab strip.
  useEffect(() => {
    if (!summary || summary === "Loading run…") return;
    document.title = state.done
      ? `${state.error ? "⚠" : "✓"} ${summary} — Buy & Build Score`
      : `${total ? `${scored}/${total}` : "…"} ${summary} — Buy & Build Score`;
  }, [summary, state.done, state.error, scored, total]);

  const label: Record<Stage, string> = {
    discovering: total ? `Discovered ${state.counts.discovered ?? total}` : "Discovering",
    crawling: total ? `Reading sites ${scored}/${total}` : "Reading sites",
    scoring: "Scoring",
    done: "Done",
  };

  return (
    <div className="border-b bg-surface">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
        <Button variant="ghost" size="icon-sm" asChild>
          <Link href="/" aria-label="New search">
            <ChevronLeftIcon />
          </Link>
        </Button>
        {/* Phones: title owns the first line; stage chips and timer wrap underneath. */}
        <div className="min-w-0 flex-1 basis-[calc(100%-3rem)] md:basis-0">
          <h1 className="truncate text-lg leading-6 font-semibold tracking-tight sm:text-xl">{summary}</h1>
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>{state.mode === "places" ? "Google Places + websites" : state.mode === "csv" ? "Your CSV + websites" : "OpenStreetMap + websites"}</span>
            {siteOnly && (
              <Tooltip>
                <TooltipTrigger className="underline decoration-dotted underline-offset-2">durability (site-only)</TooltipTrigger>
                <TooltipContent className="max-w-72">
                  No review data without a Google Places key, so durability uses founding year and a verified
                  address only, re-scaled to 0–100.
                </TooltipContent>
              </Tooltip>
            )}
            {(state.counts.chains_dropped ?? 0) > 0 && <span>· {state.counts.chains_dropped} chains filtered out</span>}
            {(state.counts.llm_calls ?? 0) > 0 && <span>· {plural(state.counts.llm_calls ?? 0, "LLM call")}</span>}
          </p>
        </div>

        <ol className="flex items-center gap-1.5 text-xs" aria-label="Run progress">
          {ORDER.map((s, i) => {
            const idx = ORDER.indexOf(stage);
            const state_ = i < idx ? "past" : i === idx ? "now" : "next";
            if (s === "scoring" && stage !== "scoring") return null;
            return (
              <li key={s} className="flex items-center gap-1.5">
                {i > 0 && <span className="h-px w-3 bg-line" aria-hidden />}
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
                    state_ === "now" && "border-foreground/20 bg-background text-foreground",
                    state_ === "past" && "text-muted-foreground",
                    state_ === "next" && "border-dashed text-muted-foreground/60",
                  )}
                  aria-current={state_ === "now" ? "step" : undefined}
                >
                  {state_ === "past" && <CheckIcon className="size-3" />}
                  {state_ === "now" && s !== "done" && !state.error && <Loader2Icon className="size-3 animate-spin" />}
                  {state_ === "now" && s === "done" && <CheckIcon className="size-3 text-tier-a" />}
                  <span className="font-mono tabular-nums">{state_ === "now" ? label[s] : label[s].split(" ")[0]}</span>
                </span>
              </li>
            );
          })}
        </ol>
        <span className="font-mono text-xs tabular-nums text-muted-foreground" aria-label="Elapsed time">
          {elapsed(ms)}
          {state.resumes > 0 && ` · resumed ×${state.resumes}`}
        </span>
      </div>
      <div className="h-0.5 bg-line" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div
          className={cn("h-full transition-[width] duration-500", state.error ? "bg-destructive" : "bg-brand")}
          style={{ width: `${pct}%` }}
        />
      </div>
      {state.error && (
        <div className="flex items-center gap-2 px-4 py-2 text-sm text-destructive sm:px-6">
          <CircleAlertIcon className="size-4" /> {state.error}
        </div>
      )}
    </div>
  );
}
