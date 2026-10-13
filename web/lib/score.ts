/**
 * Client-side re-weighting. Mirrors api/app/pipeline/score.py (composite, tier, guardrails) and
 * api/app/scoring.yaml (tiers, guardrails, presets) so sliders re-rank with no network call.
 */
import type { LeadOut, Preset, Tier, Weights } from "./types";

export const TIERS = { A: 70, B: 50 } as const;
export const GUARDRAILS = { durabilityFloor: 30, minCoverageForA: 0.4 } as const;

export const PRESETS: Record<Preset, Weights & { label: string; blurb: string }> = {
  searcher: {
    durability: 40,
    succession: 40,
    upside: 20,
    label: "Searcher",
    blurb: "Durable, founder-run businesses whose owner may want out.",
  },
  sdr: {
    durability: 25,
    succession: 10,
    upside: 65,
    label: "SDR",
    blurb: "Businesses with obvious digital gaps that will pick up the phone.",
  },
  caprae: {
    durability: 35,
    succession: 30,
    upside: 35,
    label: "Caprae",
    blurb: "Add-on acquisitions with an AI-upgrade path after close.",
  },
};

export function presetWeights(p: Preset): Weights {
  const { durability, succession, upside } = PRESETS[p];
  return { durability, succession, upside };
}

/** Same rounding as Python's floor(x + 0.5) on the API side. */
export function roundHalfUp(x: number): number {
  return Math.floor(x + 0.5);
}

export function composite(d: number, s: number, u: number, w: Weights): number {
  const total = w.durability + w.succession + w.upside;
  if (total <= 0) return 0;
  return roundHalfUp((w.durability * d + w.succession * s + w.upside * u) / total);
}

export type Cap = "durability_floor" | "thin_data" | null;

export function tierOf(comp: number, durability: number, coverage: number): { tier: Tier; capped: Cap } {
  const t: Tier = comp >= TIERS.A ? "A" : comp >= TIERS.B ? "B" : "C";
  if (t === "A") {
    if (coverage < GUARDRAILS.minCoverageForA) return { tier: "B", capped: "thin_data" };
    if (durability < GUARDRAILS.durabilityFloor) return { tier: "B", capped: "durability_floor" };
  }
  return { tier: t, capped: null };
}

export interface Ranked extends LeadOut {
  composite: number;
  tier: Tier;
  capped: Cap;
}

export function rank(lead: LeadOut, w: Weights): Ranked {
  const { durability, succession, upside } = lead.scores;
  const comp = composite(durability, succession, upside, w);
  const { tier, capped } = tierOf(comp, durability, lead.coverage);
  return { ...lead, composite: comp, tier, capped };
}

export function sameWeights(a: Weights, b: Weights): boolean {
  return a.durability === b.durability && a.succession === b.succession && a.upside === b.upside;
}

export function weightShare(w: Weights): Weights {
  const total = w.durability + w.succession + w.upside || 1;
  return {
    durability: Math.round((w.durability / total) * 100),
    succession: Math.round((w.succession / total) * 100),
    upside: Math.round((w.upside / total) * 100),
  };
}
