"use client";

import { RotateCcwIcon, SearchIcon } from "lucide-react";
import { DIM_LABEL } from "@/components/score-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { PRESETS, sameWeights, weightShare } from "@/lib/score";
import type { Preset, Tier, Weights } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type Filters, NO_FILTERS, activeFilterCount } from "./filters";

const TIER_CHIP: Record<Tier, string> = {
  A: "data-[on=true]:border-tier-a/50 data-[on=true]:bg-tier-a/10",
  B: "data-[on=true]:border-tier-b/50 data-[on=true]:bg-tier-b/10",
  C: "data-[on=true]:border-tier-c/50 data-[on=true]:bg-tier-c/10",
};
const TIER_TEXT: Record<Tier, string> = { A: "text-tier-a", B: "text-tier-b", C: "text-tier-c" };

function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex h-5 items-center justify-between">
        <h2 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function RangeRow({
  label,
  value,
  onChange,
  prefix = "≥",
  max = 100,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  prefix?: string;
  max?: number;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="flex items-baseline justify-between text-sm">
        <span>{label}</span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {prefix} {value}
        </span>
      </span>
      <Slider value={[value]} min={0} max={max} step={5} onValueChange={([v]) => onChange(v)} aria-label={label} />
    </label>
  );
}

export function FilterRail({
  filters,
  setFilters,
  tierCounts,
  weights,
  setWeights,
  preset,
  setPreset,
  className,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  tierCounts: Record<Tier, number>;
  weights: Weights;
  setWeights: (w: Weights) => void;
  preset: Preset;
  setPreset: (p: Preset) => void;
  className?: string;
}) {
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setFilters({ ...filters, [k]: v });
  const toggleTier = (t: Tier) =>
    set("tiers", filters.tiers.includes(t) ? filters.tiers.filter((x) => x !== t) : [...filters.tiers, t]);
  const custom = !sameWeights(weights, PRESETS[preset]);
  const share = weightShare(weights);
  const n = activeFilterCount(filters);

  return (
    <div className={cn("flex flex-col gap-6", className)}>
      <Section
        title="Tier"
        action={
          n > 0 ? (
            <Button variant="ghost" size="xs" onClick={() => setFilters(NO_FILTERS)}>
              Clear {n}
            </Button>
          ) : null
        }
      >
        <div className="grid grid-cols-3 gap-1.5" role="group" aria-label="Filter by tier">
          {(["A", "B", "C"] as Tier[]).map((t) => (
            <button
              key={t}
              type="button"
              data-on={filters.tiers.includes(t)}
              aria-pressed={filters.tiers.includes(t)}
              onClick={() => toggleTier(t)}
              className={cn(
                "flex items-baseline justify-center gap-1.5 rounded-md border px-2 py-1.5 text-sm transition-colors hover:border-foreground/30",
                TIER_CHIP[t],
              )}
            >
              <span className={cn("font-mono font-semibold", TIER_TEXT[t])}>{t}</span>
              <span className="font-mono text-xs tabular-nums text-muted-foreground">{tierCounts[t]}</span>
            </button>
          ))}
        </div>
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Name, domain, city, owner"
            className="h-8 pl-8 text-sm"
            aria-label="Search leads"
          />
        </div>
      </Section>

      <Separator />

      <Section title="Minimum sub-scores">
        <RangeRow label="Durability" value={filters.minD} onChange={(v) => set("minD", v)} />
        <RangeRow label="Succession" value={filters.minS} onChange={(v) => set("minS", v)} />
        <RangeRow label="Digital upside" value={filters.minU} onChange={(v) => set("minU", v)} />
      </Section>

      <Separator />

      <Section title="Show only">
        {(
          [
            ["hasOwner", "Owner name found"],
            ["validEmail", "Valid company email"],
            ["hideThin", "Hide thin data"],
          ] as const
        ).map(([k, label]) => (
          <label key={k} className="flex items-center justify-between gap-3 text-sm">
            {label}
            <Switch checked={filters[k]} onCheckedChange={(v) => set(k, v)} aria-label={label} />
          </label>
        ))}
      </Section>

      <Separator />

      <Section
        title="Weights"
        action={
          custom ? (
            <Button variant="ghost" size="xs" onClick={() => setWeights(PRESETS[preset])}>
              <RotateCcwIcon /> Reset
            </Button>
          ) : null
        }
      >
        <div className="grid grid-cols-3 rounded-md border p-0.5" role="radiogroup" aria-label="Preset">
          {(Object.keys(PRESETS) as Preset[]).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={preset === p && !custom}
              onClick={() => {
                setPreset(p);
                setWeights(PRESETS[p]);
              }}
              className={cn(
                "rounded-[5px] px-1.5 py-1 text-xs transition-colors",
                preset === p && !custom ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {PRESETS[p].label}
            </button>
          ))}
        </div>
        {(["durability", "succession", "upside"] as const).map((k) => (
          <RangeRow
            key={k}
            label={DIM_LABEL[k]}
            value={weights[k]}
            prefix={`${share[k]}% ·`}
            onChange={(v) => setWeights({ ...weights, [k]: v })}
          />
        ))}
        <p className="text-xs text-muted-foreground">
          {custom ? "Custom weights. " : `${PRESETS[preset].blurb} `}Re-ranks instantly in your browser — nothing is
          re-crawled.
        </p>
      </Section>
    </div>
  );
}
