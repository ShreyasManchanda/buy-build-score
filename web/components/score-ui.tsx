import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Cap } from "@/lib/score";
import type { Dimension, Tier } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIER_STYLE: Record<Tier, string> = {
  A: "text-tier-a border-tier-a/35 bg-tier-a/10",
  B: "text-tier-b border-tier-b/40 bg-tier-b/10",
  C: "text-tier-c border-tier-c/35 bg-tier-c/10",
};

const TIER_HELP: Record<Tier, string> = {
  A: "Tier A — composite 70+. Spend credits here first.",
  B: "Tier B — composite 50–69. Worth a look.",
  C: "Tier C — composite under 50. Lower priority, not bad.",
};

const CAP_HELP: Record<Exclude<Cap, null>, string> = {
  thin_data: "Scored A, capped at B: under 40% of signals could be checked.",
  durability_floor: "Scored A, capped at B: durability under 30 — upside on a failing business isn't upside.",
};

/** Tier is always a letter (never colour alone, WCAG 1.4.1). */
export function TierBadge({
  tier,
  capped = null,
  size = "md",
  className,
}: {
  tier: Tier;
  capped?: Cap;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const badge = (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center rounded-md border font-mono font-semibold tabular-nums",
        size === "sm" && "size-5 text-[11px]",
        size === "md" && "size-6 text-xs",
        size === "lg" && "size-9 text-base",
        TIER_STYLE[tier],
        className,
      )}
      aria-label={`Tier ${tier}${capped ? " (capped)" : ""}`}
    >
      {tier}
      {capped && (
        <span className="absolute -top-1 -right-1 size-2 rounded-full border border-background bg-muted-foreground" />
      )}
    </span>
  );
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent side="right">{capped ? CAP_HELP[capped] : TIER_HELP[tier]}</TooltipContent>
    </Tooltip>
  );
}

export const DIM_LETTER: Record<Dimension, string> = { durability: "D", succession: "S", upside: "U" };
export const DIM_LABEL: Record<Dimension, string> = {
  durability: "Durability",
  succession: "Succession",
  upside: "Digital upside",
};
export const DIM_QUESTION: Record<Dimension, string> = {
  durability: "Will this business last?",
  succession: "Might the owner sell?",
  upside: "How much can a buyer improve, fast?",
};

export function ScoreBar({ value, className }: { value: number; className?: string }) {
  return (
    <span className={cn("relative block h-1.5 w-full overflow-hidden rounded-full bg-foreground/[0.08]", className)}>
      <span
        className="absolute inset-y-0 left-0 rounded-full bg-foreground/70 transition-[width] duration-300"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </span>
  );
}

/** D/S/U mini-bars for table rows and cards. */
export function MiniBars({ d, s, u, className }: { d: number; s: number; u: number; className?: string }) {
  const rows: [string, number, string][] = [
    ["D", d, "Durability"],
    ["S", s, "Succession"],
    ["U", u, "Digital upside"],
  ];
  return (
    <div className={cn("grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-1.5 gap-y-[3px]", className)}>
      {rows.map(([k, v, label]) => (
        <div key={k} className="contents" title={`${label} ${v}/100`}>
          <span className="font-mono text-[10px] leading-none text-muted-foreground">{k}</span>
          <ScoreBar value={v} />
          <span className="w-5 text-right font-mono text-[10px] leading-none tabular-nums text-muted-foreground">
            {v}
          </span>
        </div>
      ))}
    </div>
  );
}

export function EvidenceChip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center truncate rounded-md border bg-surface-2/60 px-1.5 py-px text-[11px] leading-4 text-muted-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Confidence as a filled dot: solid ≥ 0.9, half ≥ 0.7, ring below. */
export function ConfidenceDot({ value }: { value: number }) {
  const label = `${Math.round(value * 100)}% confidence`;
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "inline-block size-2 shrink-0 rounded-full border border-foreground/50",
        value >= 0.9 && "bg-foreground/70",
        value >= 0.7 && value < 0.9 && "bg-[linear-gradient(90deg,var(--color-foreground)_50%,transparent_50%)] opacity-70",
      )}
    />
  );
}
