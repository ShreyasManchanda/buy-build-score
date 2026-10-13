/**
 * Client-side CSV (fallback for the static demo when the API is unreachable).
 * Same columns as POST /api/v1/export/csv: SaaSquatch-compatible + scores + top 3 evidence. UTF-8 BOM.
 */
import type { Ranked } from "./score";
import type { LeadDetail } from "./types";

export const CSV_COLUMNS = [
  "Company",
  "Website",
  "Phone",
  "Address",
  "City",
  "State",
  "Founded",
  "Owner",
  "Rating",
  "Reviews",
  "Tier",
  "Composite",
  "Durability",
  "Succession",
  "Upside",
  "Coverage",
  "Email Status",
  "Evidence 1",
  "Evidence 2",
  "Evidence 3",
  "Run ID",
];

function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  // Neutralise spreadsheet formula injection, then quote. Phone numbers / plain numbers stay intact.
  const numeric = /^[+-][\d\s().-]*\d[\d\s().-]*$/.test(s);
  const safe = !numeric && /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function evidenceLines(d: LeadDetail | undefined): string[] {
  if (!d) return [];
  return [...d.evidence]
    .filter((e) => e.points > 0)
    .sort((a, b) => b.points - a.points)
    .slice(0, 3)
    .map((e) => `${e.label}: ${e.value ?? ""} (${e.source_url ?? ""})`);
}

export function toCsv(leads: Ranked[], details: Map<string, LeadDetail>, runId: string): string {
  const rows = [CSV_COLUMNS.join(",")];
  for (const l of leads) {
    const d = details.get(l.id);
    const ev = evidenceLines(d);
    rows.push(
      [
        l.name,
        l.website,
        l.phone,
        d?.address,
        l.city,
        l.region,
        l.founded_year,
        l.owner_name,
        l.rating,
        l.review_count,
        l.tier,
        l.composite,
        l.scores.durability,
        l.scores.succession,
        l.scores.upside,
        `${Math.round(l.coverage * 100)}%`,
        l.email_status,
        ev[0],
        ev[1],
        ev[2],
        runId,
      ]
        .map(cell)
        .join(","),
    );
  }
  return "﻿" + rows.join("\r\n") + "\r\n";
}
