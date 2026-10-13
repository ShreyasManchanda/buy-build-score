import type { Ranked } from "@/lib/score";
import type { Tier } from "@/lib/types";

export interface Filters {
  tiers: Tier[]; // empty = all
  q: string;
  minD: number;
  minS: number;
  minU: number;
  hasOwner: boolean;
  validEmail: boolean;
  hideThin: boolean;
}

export const NO_FILTERS: Filters = {
  tiers: [],
  q: "",
  minD: 0,
  minS: 0,
  minU: 0,
  hasOwner: false,
  validEmail: false,
  hideThin: false,
};

export type SortKey = "composite" | "durability" | "succession" | "upside" | "name" | "founded";
export interface Sort {
  key: SortKey;
  desc: boolean;
}

/** Everything except the tier filter (tier chip counts are computed on this set). */
export function passesBase(l: Ranked, f: Filters): boolean {
  if (l.scores.durability < f.minD || l.scores.succession < f.minS || l.scores.upside < f.minU) return false;
  if (f.hasOwner && !l.owner_name) return false;
  if (f.validEmail && l.email_status !== "valid_mx") return false;
  if (f.hideThin && l.thin_data) return false;
  if (f.q) {
    const q = f.q.toLowerCase();
    const hay = `${l.name} ${l.domain ?? ""} ${l.city ?? ""} ${l.owner_name ?? ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

export function compare(a: Ranked, b: Ranked, s: Sort): number {
  const dir = s.desc ? -1 : 1;
  const val = (l: Ranked): number | string | null => {
    switch (s.key) {
      case "composite":
        return l.composite;
      case "durability":
        return l.scores.durability;
      case "succession":
        return l.scores.succession;
      case "upside":
        return l.scores.upside;
      case "founded":
        return l.founded_year;
      case "name":
        return l.name.toLowerCase();
    }
  };
  const va = val(a);
  const vb = val(b);
  if (va === null && vb !== null) return 1; // nulls last regardless of direction
  if (vb === null && va !== null) return -1;
  if (va !== null && vb !== null && va !== vb) return (va < vb ? -1 : 1) * dir;
  // Stable tie-breaks: higher coverage first, then name.
  if (a.coverage !== b.coverage) return b.coverage - a.coverage;
  return a.name.localeCompare(b.name);
}

export function activeFilterCount(f: Filters): number {
  return (
    (f.tiers.length ? 1 : 0) +
    (f.q ? 1 : 0) +
    (f.minD || f.minS || f.minU ? 1 : 0) +
    (f.hasOwner ? 1 : 0) +
    (f.validEmail ? 1 : 0) +
    (f.hideThin ? 1 : 0)
  );
}
