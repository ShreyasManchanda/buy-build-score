"use client";

import {
  ArrowUpRightIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  DownloadIcon,
  GlobeIcon,
  MailIcon,
  MapPinIcon,
  PhoneIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  UserRoundIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  ConfidenceDot,
  DIM_LABEL,
  DIM_QUESTION,
  EvidenceChip,
  ScoreBar,
  TierBadge,
} from "@/components/score-ui";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { CRAWL_LABEL, EXTRACTOR_LABEL, formatPhone, host, path } from "@/lib/format";
import type { Ranked } from "@/lib/score";
import type { Dimension, EvidenceOut, LeadDetail, MissingSignal, Weights } from "@/lib/types";
import { cn } from "@/lib/utils";

const LeadMap = dynamic(() => import("./lead-map"), {
  ssr: false,
  loading: () => <Skeleton className="h-36 w-full rounded-lg" />,
});

const DIMS: Dimension[] = ["durability", "succession", "upside"];

function EvidenceRow({ e }: { e: EvidenceOut }) {
  const earned = e.points > 0;
  const row = (
    <li
      className={cn(
        "grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2.5 rounded-md px-2 py-1.5 text-[13px]",
        "hover:bg-surface-2/70",
      )}
    >
      <span className="min-w-0">
        <span className={cn("block truncate", !earned && "text-muted-foreground")}>{e.label}</span>
        {e.value && <span className="block truncate text-xs text-muted-foreground">{e.value}</span>}
      </span>
      <span
        className={cn(
          "font-mono text-xs tabular-nums",
          earned ? "font-semibold text-foreground" : "text-muted-foreground",
        )}
        title={`${e.points} of ${e.max_points} points`}
      >
        {earned ? `+${trim(e.points)}` : "0"}
      </span>
      <ConfidenceDot value={e.confidence} />
      {e.source_url ? (
        <a
          href={e.source_url}
          target="_blank"
          rel="noreferrer"
          onClick={(ev) => ev.stopPropagation()}
          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-background hover:text-foreground"
          aria-label={`Open source for ${e.label}`}
        >
          <ArrowUpRightIcon className="size-3.5" />
        </a>
      ) : (
        <span className="size-6" />
      )}
    </li>
  );
  if (!e.snippet) return row;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{row}</TooltipTrigger>
      <TooltipContent side="left" className="max-w-80 text-xs leading-5">
        <span className="mb-1 block text-[10px] tracking-wide uppercase opacity-70">
          {EXTRACTOR_LABEL[e.extractor] ?? e.extractor} · {path(e.source_url)}
        </span>
        {e.snippet}
      </TooltipContent>
    </Tooltip>
  );
}

function MissingRow({ m }: { m: MissingSignal }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-2 rounded-md px-2 py-1 text-[13px] text-muted-foreground/70">
      <span className="truncate">{m.label}</span>
      <span className="text-xs italic">not found · 0/{trim(m.max_points)}</span>
    </li>
  );
}

function trim(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function DimensionSection({
  dim,
  score,
  evidence,
  missing,
  siteOnly,
}: {
  dim: Dimension;
  score: number;
  evidence: EvidenceOut[];
  missing: MissingSignal[];
  siteOnly: boolean;
}) {
  const [open, setOpen] = useState(true);
  const rows = [...evidence].sort((a, b) => b.points - a.points);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-t">
      <CollapsibleTrigger className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-surface-2/40">
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="font-medium">{DIM_LABEL[dim]}</span>
            {dim === "durability" && siteOnly && <span className="text-xs text-muted-foreground">(site-only)</span>}
          </span>
          <span className="block text-xs text-muted-foreground">{DIM_QUESTION[dim]}</span>
        </span>
        <span className="w-20">
          <ScoreBar value={score} />
        </span>
        <span className="w-8 text-right font-mono text-base font-semibold tabular-nums">{score}</span>
        <ChevronDownIcon className={cn("size-4 text-muted-foreground transition-transform", !open && "-rotate-90")} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="flex flex-col px-3 pb-3">
          {rows.map((e) => (
            <EvidenceRow key={e.signal} e={e} />
          ))}
          {missing.map((m) => (
            <MissingRow key={m.signal} m={m} />
          ))}
          {rows.length === 0 && missing.length === 0 && (
            <li className="px-2 py-1 text-xs text-muted-foreground">No signals.</li>
          )}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Fact({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex min-w-0 items-start gap-2 text-[13px]">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-3.5">{icon}</span>
      <span className="min-w-0 flex-1">{children}</span>
    </li>
  );
}

export function LeadDrawer({
  lead,
  weights,
  preloaded,
  onClose,
  onPrev,
  onNext,
  onExport,
}: {
  lead: Ranked | null;
  weights: Weights;
  preloaded?: LeadDetail;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onExport: (ids: string[]) => void;
}) {
  const [fetched, setFetched] = useState<{ id: string; detail: LeadDetail | null; error?: string } | null>(null);
  const id = lead?.id ?? null;

  useEffect(() => {
    if (!id || preloaded) return;
    let cancelled = false;
    api
      .lead(id, weights)
      .then((d) => !cancelled && setFetched({ id, detail: d }))
      .catch((e: Error) => !cancelled && setFetched({ id, detail: null, error: e.message }));
    return () => {
      cancelled = true;
    };
    // Weights don't change evidence; re-fetching on every slider move would be wasteful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, preloaded]);

  const detail = preloaded ?? (fetched?.id === id ? fetched.detail : null);
  const loadError = fetched?.id === id ? fetched.error : undefined;

  async function vote(v: 1 | -1) {
    if (!lead) return;
    try {
      await api.feedback(lead.id, v);
      toast.success("Thanks — feedback saved", { description: "It will tune future weights." });
    } catch {
      toast.error("Couldn't save feedback");
    }
  }

  return (
    <Sheet open={Boolean(lead)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[480px] data-[side=right]:sm:max-w-[480px]"
        aria-describedby={undefined}
      >
        {lead && (
          <>
            <SheetHeader className="gap-3 px-5 pt-5 pb-4">
              <div className="flex items-start gap-3 pr-8">
                <TierBadge tier={lead.tier} capped={lead.capped} size="lg" />
                <div className="min-w-0 flex-1">
                  <SheetTitle className="text-lg leading-6 font-semibold tracking-tight">{lead.name}</SheetTitle>
                  <SheetDescription className="text-xs">
                    {[lead.city, lead.region].filter(Boolean).join(", ") || "Location not listed"}
                    {lead.founded_year ? ` · since ${lead.founded_year}` : ""}
                  </SheetDescription>
                </div>
                <div className="text-right">
                  <div className="font-mono text-3xl leading-8 font-semibold tabular-nums">{lead.composite}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {weights.durability}/{weights.succession}/{weights.upside} weights
                  </div>
                </div>
              </div>
              {lead.capped && (
                <p className="rounded-md border border-dashed px-2.5 py-1.5 text-xs text-muted-foreground">
                  {lead.capped === "thin_data"
                    ? "Scores like an A, capped at B: fewer than 40% of signals could be checked."
                    : "Scores like an A, capped at B: durability is under 30, so upside isn't real upside yet."}
                </p>
              )}
              {lead.crawl_status && lead.crawl_status !== "ok" && (
                <p className="rounded-md border border-warn/30 bg-warn/5 px-2.5 py-1.5 text-xs text-warn">
                  {CRAWL_LABEL[lead.crawl_status]}
                </p>
              )}

              <ul className="flex flex-col gap-1.5">
                {(detail?.address || lead.city) && (
                  <Fact icon={<MapPinIcon />}>{detail?.address ?? [lead.city, lead.region].filter(Boolean).join(", ")}</Fact>
                )}
                {lead.website && (
                  <Fact icon={<GlobeIcon />}>
                    <a href={lead.website} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                      {host(lead.website)}
                    </a>
                  </Fact>
                )}
                {lead.phone && (
                  <Fact icon={<PhoneIcon />}>
                    <a href={`tel:${lead.phone}`} className="font-mono text-xs underline-offset-2 hover:underline">
                      {formatPhone(lead.phone)}
                    </a>
                    {lead.phone_valid === false && <span className="ml-1.5 text-xs text-muted-foreground">(looks invalid)</span>}
                  </Fact>
                )}
                {detail?.email && (
                  <Fact icon={<MailIcon />}>
                    <span className="break-all">{detail.email}</span>{" "}
                    <span className="text-xs text-muted-foreground">
                      {lead.email_status === "valid_mx" ? "· domain accepts mail" : lead.email_status === "no_mx" ? "· no mail server" : ""}
                    </span>
                  </Fact>
                )}
                <Fact icon={<UserRoundIcon />}>
                  {lead.owner_name ? (
                    <>
                      <span className="font-medium">{lead.owner_name}</span>
                      {detail?.owner_title && <span className="text-muted-foreground"> · {detail.owner_title}</span>}
                      {detail?.owner_source_url && (
                        <a
                          href={detail.owner_source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-1.5 inline-flex items-center gap-0.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                        >
                          found on {path(detail.owner_source_url)}
                          <ArrowUpRightIcon className="size-3" />
                        </a>
                      )}
                    </>
                  ) : (
                    <span className="text-muted-foreground">Owner not named on the site</span>
                  )}
                </Fact>
              </ul>
              {lead.lat !== null && lead.lng !== null && <LeadMap lat={lead.lat} lng={lead.lng} label={lead.name} />}
            </SheetHeader>

            {!detail && !loadError && (
              <div className="flex flex-col gap-2 border-t px-5 py-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            )}
            {loadError && <p className="border-t px-5 py-4 text-sm text-destructive">{loadError}</p>}

            {detail && (
              <div className="flex flex-col">
                {DIMS.map((d) => (
                  <DimensionSection
                    key={d}
                    dim={d}
                    score={lead.scores[d]}
                    evidence={detail.evidence.filter((e) => e.dimension === d)}
                    missing={detail.missing.filter((m) => m.dimension === d)}
                    siteOnly={lead.durability_mode === "site_only"}
                  />
                ))}
                <div className="flex flex-col gap-3 border-t px-5 py-4">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>
                      Coverage <span className="font-mono tabular-nums">{Math.round(lead.coverage * 100)}%</span> of
                      signals checked
                    </span>
                    <span className="flex items-center gap-1.5">
                      <ConfidenceDot value={0.9} /> rule <ConfidenceDot value={0.7} /> LLM
                    </span>
                  </div>
                  {detail.tech.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="mr-1 text-xs text-muted-foreground">Stack</span>
                      {detail.tech.map((t) => (
                        <EvidenceChip key={t}>{t}</EvidenceChip>
                      ))}
                    </div>
                  )}
                  {detail.services.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="mr-1 text-xs text-muted-foreground">Services</span>
                      {detail.services.map((t) => (
                        <EvidenceChip key={t}>{t}</EvidenceChip>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="sticky bottom-0 mt-auto flex items-center gap-2 border-t bg-popover/95 px-5 py-3 backdrop-blur">
              <Button variant="outline" size="icon-sm" onClick={onPrev} disabled={!onPrev} aria-label="Previous lead (↑)">
                <ChevronUpIcon />
              </Button>
              <Button variant="outline" size="icon-sm" onClick={onNext} disabled={!onNext} aria-label="Next lead (↓)">
                <ChevronDownIcon />
              </Button>
              <span className="hidden text-xs text-muted-foreground sm:inline">↑↓ to move · E to export</span>
              <span className="flex-1" />
              <Button variant="ghost" size="icon-sm" onClick={() => vote(1)} aria-label="Tier looks right">
                <ThumbsUpIcon />
              </Button>
              <Button variant="ghost" size="icon-sm" onClick={() => vote(-1)} aria-label="Tier looks wrong">
                <ThumbsDownIcon />
              </Button>
              <Button size="sm" onClick={() => onExport([lead.id])}>
                <DownloadIcon /> Export
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
