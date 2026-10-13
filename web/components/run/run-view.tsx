"use client";

import { DownloadIcon, ListFilterIcon, Loader2Icon, PlayIcon, SearchXIcon, ShieldCheckIcon, TriangleAlertIcon, UploadCloudIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AppHeader, AttributionFooter } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, ApiError, downloadBlob } from "@/lib/api";
import { toCsv } from "@/lib/csv";
import { plural } from "@/lib/format";
import { PRESETS, rank, type Ranked } from "@/lib/score";
import type { Health, Preset, Tier, Weights } from "@/lib/types";
import { useRun } from "@/lib/use-run";
import { cn } from "@/lib/utils";
import { FilterRail } from "./filter-rail";
import { type Filters, NO_FILTERS, type Sort, type SortKey, activeFilterCount, compare, passesBase } from "./filters";
import { LeadDrawer } from "./lead-drawer";
import { LeadCards, LeadTable } from "./lead-table";
import { RunHeader } from "./run-header";

function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const on = () => setMobile(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return mobile;
}

export function RunView({ runId }: { runId: string }) {
  const router = useRouter();
  const state = useRun(runId);
  const mobile = useIsMobile();

  const [preset, setPreset] = useState<Preset | null>(null);
  const [weightsOverride, setWeightsOverride] = useState<Weights | null>(null);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [sort, setSort] = useState<Sort>({ key: "composite", desc: true });
  const [interacted, setInteracted] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);

  const activePreset: Preset = preset ?? state.run?.preset ?? "searcher";
  const weights: Weights = weightsOverride ?? PRESETS[activePreset];

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  // ---- ranking (pure, in-browser; no network on slider moves)
  const ranked = useMemo(() => {
    const out: Ranked[] = [];
    for (const l of state.leads.values()) out.push(rank(l, weights));
    return out;
  }, [state.leads, weights]);

  const base = useMemo(() => ranked.filter((l) => passesBase(l, filters)), [ranked, filters]);
  const tierCounts = useMemo(() => {
    const c: Record<Tier, number> = { A: 0, B: 0, C: 0 };
    for (const l of base) c[l.tier]++;
    return c;
  }, [base]);

  const frozen = !state.done && !interacted;
  const rows = useMemo(() => {
    const visible = filters.tiers.length ? base.filter((l) => filters.tiers.includes(l.tier)) : base;
    if (frozen) {
      // Streaming: keep arrival order so rows don't jump under the cursor.
      const pos = new Map(state.arrival.map((id, i) => [id, i]));
      return [...visible].sort((a, b) => (pos.get(a.id) ?? 0) - (pos.get(b.id) ?? 0));
    }
    return [...visible].sort((a, b) => compare(a, b, sort));
  }, [base, filters.tiers, frozen, sort, state.arrival]);

  const byId = useMemo(() => new Map(ranked.map((l) => [l.id, l])), [ranked]);
  const openLead = openId ? (byId.get(openId) ?? null) : null;
  const openIndex = openId ? rows.findIndex((r) => r.id === openId) : -1;

  // ---- interactions
  const touch = () => setInteracted(true);
  const onSort = (k: SortKey) => {
    touch();
    setSort((s) => (s.key === k ? { key: k, desc: !s.desc } : { key: k, desc: k !== "name" }));
  };
  const setWeights = (w: Weights) => {
    touch();
    setWeightsOverride(w);
  };
  const choosePreset = (p: Preset) => {
    touch();
    setPreset(p);
    setWeightsOverride(null);
  };
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleAll = (on: boolean) => setSelected(on ? new Set(rows.map((r) => r.id)) : new Set());

  const exportIds = useCallback(
    async (ids: string[]) => {
      if (!ids.length) return;
      setExporting(true);
      const name = `buy-build-score-${runId === "demo" ? "demo" : runId.slice(0, 8)}.csv`;
      try {
        if (runId === "demo") await api.createDemoRun(); // idempotent: makes the demo exist server-side
        downloadBlob(await api.exportCsv(ids, weights), name);
        toast.success(`Exported ${plural(ids.length, "lead")}`, { description: "Opens cleanly in Excel and Google Sheets." });
      } catch {
        if (state.details.size) {
          const chosen = ids.map((id) => byId.get(id)).filter(Boolean) as Ranked[];
          downloadBlob(new Blob([toCsv(chosen, state.details, runId)], { type: "text/csv;charset=utf-8" }), name);
          toast.success(`Exported ${plural(ids.length, "lead")}`, { description: "Built in your browser (API offline)." });
        } else {
          toast.error("Export failed", { description: "The API didn't respond. Try again in a moment." });
        }
      } finally {
        setExporting(false);
      }
    },
    [runId, weights, state.details, byId],
  );

  async function pushHubspot(ids: string[]) {
    const t = toast.loading(`Pushing ${plural(ids.length, "company", "companies")} to HubSpot…`);
    try {
      if (runId === "demo") await api.createDemoRun();
      const r = await api.exportHubspot(ids, weights);
      toast.success(`HubSpot: ${r.created} created, ${r.updated} updated`, {
        id: t,
        description: r.failed.length ? `${r.failed.length} failed — ${r.failed[0].reason}` : "Upserted on domain; scores in bbs_* properties.",
      });
    } catch (e) {
      toast.error("HubSpot push failed", { id: t, description: (e as ApiError).detail ?? (e as Error).message });
    }
  }

  // ---- keyboard: ↑/↓ next/prev lead in the drawer, E export, Esc handled by the sheet
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) return;
      if (openId && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        const next = rows[openIndex + (e.key === "ArrowDown" ? 1 : -1)];
        if (next) setOpenId(next.id);
      } else if (e.key === "e" || e.key === "E") {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        const ids = selected.size ? [...selected] : openId ? [openId] : [];
        if (ids.length) void exportIds(ids);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openId, openIndex, rows, selected, exportIds]);

  async function widen() {
    const q = state.run?.query;
    if (!q?.industry || !q.location) return;
    try {
      const { run_id } = await api.createRun({
        industry: q.industry,
        location: q.location,
        radius_km: Math.min(100, (q.radius_km ?? 40) * 2),
        max_results: (q.max_results as 20 | 40 | 60) ?? 60,
        expand: true,
        preset: activePreset,
      });
      router.push(`/runs/${run_id}`);
    } catch (e) {
      toast.error((e as ApiError).title, { description: (e as ApiError).detail });
    }
  }

  const upstream = state.warnings.filter((w) => w.upstream || !w.company);
  const blocked = state.counts.blocked_robots ?? 0;
  const unreachable = (state.counts.unreachable ?? 0) + (state.counts.no_site ?? 0);
  const empty = state.done && !state.error && state.leads.size === 0;
  const loadingFirst = !state.done && state.leads.size === 0 && !state.error;
  const showReviews = state.mode === "places";
  const nFilters = activeFilterCount(filters);

  const rail = (
    <FilterRail
      filters={filters}
      setFilters={(f) => {
        touch();
        setFilters(f);
      }}
      tierCounts={tierCounts}
      weights={weights}
      setWeights={setWeights}
      preset={activePreset}
      setPreset={choosePreset}
    />
  );

  return (
    <div className="flex h-dvh flex-col">
      <AppHeader>
        <span className="hidden truncate text-sm text-muted-foreground lg:block" />
      </AppHeader>
      <RunHeader state={state} />

      {(upstream.length > 0 || blocked > 0 || unreachable > 0) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-2 text-xs sm:px-6">
          {upstream.map((w) => (
            <span key={w.reason} className="flex items-center gap-1.5 font-medium text-warn">
              <TriangleAlertIcon className="size-3.5" /> {w.reason}
            </span>
          ))}
          {blocked > 0 && (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <ShieldCheckIcon className="size-3.5" />
              {plural(blocked, "site")} asked crawlers to stay out (robots.txt) — respected and labelled
            </span>
          )}
          {unreachable > 0 && (
            <span className="text-muted-foreground">
              {plural(unreachable, "business", "businesses")} without a readable website — scored from listing data only
            </span>
          )}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[240px] shrink-0 overflow-y-auto border-r p-4 md:block" aria-label="Filters and weights">
          {rail}
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b px-4 py-2 sm:px-6">
            <Button variant="outline" size="sm" className="md:hidden" onClick={() => setFiltersOpen(true)}>
              <ListFilterIcon /> Filters{nFilters ? ` · ${nFilters}` : ""}
            </Button>
            <p className="text-xs text-muted-foreground">
              <span className="font-mono tabular-nums text-foreground">{rows.length}</span>
              {rows.length !== ranked.length && <span className="font-mono tabular-nums"> of {ranked.length}</span>} leads
              {frozen && ranked.length > 0 && " · arriving live"}
              {!frozen && ` · by ${sort.key === "composite" ? "score" : sort.key}`}
            </p>
            <span className="flex-1" />
            {frozen && ranked.length > 1 && (
              <Button variant="secondary" size="sm" onClick={touch}>
                Rank now
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={!rows.length || exporting}
              onClick={() => exportIds(rows.map((r) => r.id))}
              title="Export the leads shown (filters applied)"
            >
              {exporting ? <Loader2Icon className="animate-spin" /> : <DownloadIcon />}
              <span className="hidden sm:inline">Export shown</span>
            </Button>
          </div>

          <div className="min-h-0 flex-1">
            {state.error && state.leads.size === 0 ? (
              <EmptyState
                icon={<TriangleAlertIcon />}
                title="This run couldn't finish"
                body={state.error}
                actions={
                  <>
                    <Button onClick={() => window.location.reload()}>Retry</Button>
                    <Button variant="outline" asChild>
                      <Link href="/">New search</Link>
                    </Button>
                    <Button variant="outline" asChild>
                      <Link href="/runs/demo">Open the demo run</Link>
                    </Button>
                  </>
                }
              />
            ) : empty ? (
              <EmptyState
                icon={<SearchXIcon />}
                title={
                  state.run?.query.industry
                    ? `No businesses found for ${state.run.query.industry} within ${state.run.query.radius_km ?? 40} km of ${state.run.query.location}.`
                    : "No businesses found."
                }
                body="OpenStreetMap coverage varies by trade and town. Widen the radius, try a related keyword, or upload your own list."
                actions={
                  <>
                    {(state.run?.query.radius_km ?? 40) < 100 && <Button onClick={widen}>Widen radius and expand keywords</Button>}
                    <Button variant="outline" asChild>
                      <Link href="/">
                        <UploadCloudIcon /> Upload a CSV
                      </Link>
                    </Button>
                  </>
                }
              />
            ) : loadingFirst ? (
              <LoadingRows status={state.status} />
            ) : mobile ? (
              <div className="h-full overflow-y-auto">
                <LeadCards rows={rows} onOpen={setOpenId} selected={selected} onToggle={toggle} fresh={state.fresh} />
              </div>
            ) : (
              <LeadTable
                rows={rows}
                sort={sort}
                sortActive={!frozen}
                onSort={onSort}
                selected={selected}
                onToggle={toggle}
                onToggleAll={toggleAll}
                onOpen={setOpenId}
                openId={openId}
                fresh={state.fresh}
                showReviews={showReviews}
              />
            )}
          </div>
          <AttributionFooter places={showReviews} />
        </main>
      </div>

      {selected.size > 0 && (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
          <div
            role="toolbar"
            aria-label="Selection actions"
            className="pointer-events-auto flex items-center gap-2 rounded-xl border bg-popover px-3 py-2 shadow-lg animate-row-in"
          >
            <span className="px-1 text-sm whitespace-nowrap">
              <span className="font-mono tabular-nums">{selected.size}</span> selected
            </span>
            <Button size="sm" onClick={() => exportIds([...selected])} disabled={exporting}>
              {exporting ? <Loader2Icon className="animate-spin" /> : <DownloadIcon />}
              <span className="sm:hidden">CSV</span>
              <span className="hidden sm:inline">Export CSV</span>
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!health?.mode.hubspot}
                    onClick={() => pushHubspot([...selected])}
                  >
                    <HubspotGlyph /> <span className="hidden sm:inline">Push to</span> HubSpot
                  </Button>
                </span>
              </TooltipTrigger>
              {!health?.mode.hubspot && <TooltipContent>Add a HUBSPOT_TOKEN on the server to enable</TooltipContent>}
            </Tooltip>
            <Button size="icon-sm" variant="ghost" onClick={() => setSelected(new Set())} aria-label="Clear selection">
              <XIcon />
            </Button>
          </div>
        </div>
      )}

      <Sheet open={filtersOpen} onOpenChange={setFiltersOpen}>
        <SheetContent side="left" className="w-full overflow-y-auto data-[side=left]:w-full data-[side=left]:sm:max-w-sm">
          <SheetHeader className="px-4 pb-0">
            <SheetTitle>Filters &amp; weights</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-6">{rail}</div>
        </SheetContent>
      </Sheet>

      <LeadDrawer
        lead={openLead}
        weights={weights}
        preloaded={openId ? state.details.get(openId) : undefined}
        onClose={() => setOpenId(null)}
        onPrev={openIndex > 0 ? () => setOpenId(rows[openIndex - 1].id) : undefined}
        onNext={openIndex >= 0 && openIndex < rows.length - 1 ? () => setOpenId(rows[openIndex + 1].id) : undefined}
        onExport={exportIds}
        ensureServer={runId === "demo" ? api.createDemoRun : undefined}
      />
    </div>
  );
}

function HubspotGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-3.5 fill-current">
      <path d="M17.6 8.2V5.9a1.8 1.8 0 1 0-1.4 0v2.3a5.1 5.1 0 0 0-2.4 1.1L7.3 4.3a2 2 0 1 0-.9 1.1l6.3 4.9a5.1 5.1 0 0 0 .1 5.8l-1.9 1.9a1.6 1.6 0 1 0 1 1l1.9-1.9a5.1 5.1 0 1 0 3.8-8.9Zm-.7 7.7a2.6 2.6 0 1 1 0-5.3 2.6 2.6 0 0 1 0 5.3Z" />
    </svg>
  );
}

function EmptyState({
  icon,
  title,
  body,
  actions,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <span className="flex size-10 items-center justify-center rounded-full border text-muted-foreground [&_svg]:size-5">
        {icon}
      </span>
      <h2 className="max-w-[44ch] text-base font-semibold text-balance">{title}</h2>
      <p className="max-w-[56ch] text-sm text-muted-foreground text-pretty">{body}</p>
      {actions && <div className="mt-2 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

function LoadingRows({ status }: { status: string }) {
  const copy =
    status === "discovering" || status === "connecting" || status === "queued"
      ? "Finding businesses on OpenStreetMap. The public servers can take up to a minute."
      : "Reading websites politely — one request per second per site. Rows appear as each one is scored.";
  return (
    <div className="flex h-full flex-col">
      <p className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground sm:px-6">
        <Loader2Icon className="size-4 animate-spin" /> {copy}
      </p>
      <div className="flex flex-col">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className={cn("flex items-center gap-4 border-b px-4 py-3 sm:px-6", i > 3 && "opacity-60")}>
            <Skeleton className="size-6" />
            <Skeleton className="h-4 w-48" />
            <Skeleton className="ml-auto h-4 w-10" />
            <Skeleton className="hidden h-6 w-32 sm:block" />
          </div>
        ))}
      </div>
      <div className="mt-auto hidden px-6 py-4 text-xs text-muted-foreground sm:block">
        <PlayIcon className="mr-1 inline size-3" /> Tip: open the{" "}
        <Link href="/runs/demo" className="underline underline-offset-2">
          demo run
        </Link>{" "}
        in another tab while this one works.
      </div>
    </div>
  );
}
