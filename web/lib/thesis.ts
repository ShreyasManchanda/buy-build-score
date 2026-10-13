/**
 * Rules-only plain-English thesis parsing (FR-17 fallback, no LLM needed):
 * "HVAC companies near Columbus, OH" -> { industry: "HVAC", location: "Columbus, OH" }
 * "landscaping cos in Austin within 25 miles" -> { industry: "landscaping", location: "Austin", radiusKm: 40 }
 */
export interface ParsedThesis {
  industry?: string;
  location?: string;
  radiusKm?: number;
}

const FILLER = /\b(companies|company|businesses|business|shops|shop|cos|firms|firm|contractors|services|owners|owner-operated|independent|family[- ]owned)\b/gi;

export function parseThesis(text: string): ParsedThesis {
  const t = text.trim();
  if (!t) return {};
  const out: ParsedThesis = {};
  let rest = t;

  const radius = /\bwithin\s+(\d{1,3})\s*(km|kilometers?|mi|miles?)\b/i.exec(rest);
  if (radius) {
    const n = Number(radius[1]);
    out.radiusKm = Math.min(100, Math.round(/^mi/i.test(radius[2]) ? n * 1.609 : n));
    rest = rest.replace(radius[0], " ");
  }
  // Drop trailing qualifiers like "around 20 yrs old" — not a location.
  rest = rest.replace(/\b(around|about|over|at least)\s+\d+\+?\s*(yrs?|years?)\s*old\b/gi, " ");

  const split = /\s+(?:near|in|around|across|serving)\s+/i.exec(rest);
  if (split) {
    out.industry = clean(rest.slice(0, split.index).replace(FILLER, " "));
    out.location = clean(rest.slice(split.index + split[0].length));
  } else {
    out.industry = clean(rest.replace(FILLER, " "));
  }
  if (!out.industry) delete out.industry;
  if (!out.location) delete out.location;
  return out;
}

function clean(s: string): string {
  return s.replace(/\s+/g, " ").replace(/^[\s,.-]+|[\s,.-]+$/g, "").trim();
}

/** Mirrors api/app/pipeline/csv_import.py ALIASES for the client-side header preview. */
export const CSV_ALIASES: Record<string, string[]> = {
  name: ["company", "company name", "business name", "name", "organization", "account name"],
  website: ["website", "domain", "url", "company website", "company domain", "web"],
  phone: ["phone", "phone number", "company phone", "main phone", "telephone"],
  city: ["city", "town"],
  region: ["state", "region", "province", "state/region"],
  location: ["location", "hq location", "address"],
  postcode: ["zip", "zip code", "postal code", "postcode"],
  email: ["company email", "email", "generic email"],
  revenue_est: ["revenue", "estimated revenue", "annual revenue", "revenue range"],
  industry: ["industry"],
};

export function mapHeaders(headers: string[]): { mapping: Record<string, string>; unmapped: string[] } {
  const norm = (h: string) => h.trim().toLowerCase().replace(/_/g, " ").replace(/\s+/g, " ");
  const byNorm = new Map(headers.filter(Boolean).map((h) => [norm(h), h]));
  const mapping: Record<string, string> = {};
  const used = new Set<string>();
  for (const [field, aliases] of Object.entries(CSV_ALIASES)) {
    for (const a of aliases) {
      const h = byNorm.get(a);
      if (h && !used.has(h)) {
        mapping[field] = h;
        used.add(h);
        break;
      }
    }
  }
  return { mapping, unmapped: headers.filter((h) => h && !used.has(h)) };
}

/** Minimal CSV header + row count read (quotes-aware for the header line). */
export function sniffCsv(text: string): { headers: string[]; rows: number } {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  const headers: string[] = [];
  let cur = "";
  let q = false;
  for (const ch of lines[0] ?? "") {
    if (ch === '"') q = !q;
    else if (ch === "," && !q) {
      headers.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  if (lines[0]) headers.push(cur.trim());
  return { headers, rows: Math.max(0, lines.length - 1) };
}
