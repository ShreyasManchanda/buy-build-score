import type { CrawlStatus, RunOut } from "./types";

export function formatPhone(e164: string | null): string | null {
  if (!e164) return null;
  const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(e164);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : e164;
}

export function host(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function path(url: string | null): string {
  if (!url) return "";
  try {
    const u = new URL(url);
    return u.pathname === "/" ? u.host.replace(/^www\./, "") : u.pathname.replace(/\/$/, "");
  } catch {
    return url;
  }
}

export function elapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

export function thesisSummary(run: RunOut | null): string {
  if (!run) return "";
  const q = run.query;
  if (run.source === "csv") return `CSV import · ${q.filename ?? "upload"}`;
  if (run.source === "demo" || run.mode === "demo") {
    return [cap(q.industry), q.location].filter(Boolean).join(" · ") + " · demo";
  }
  return [cap(q.industry), q.location, q.radius_km ? `${q.radius_km} km` : null].filter(Boolean).join(" · ");
}

export function cap(s?: string | null): string {
  if (!s) return "";
  return s.length <= 4 ? s.toUpperCase() : s.charAt(0).toUpperCase() + s.slice(1);
}

export const CRAWL_LABEL: Record<CrawlStatus, string> = {
  ok: "Website read",
  partial: "Some pages couldn't be read",
  blocked_robots: "robots.txt asks crawlers not to read this site — respected, not crawled",
  unreachable: "Website didn't respond (or blocks bots) — scored from discovery data only",
  no_site: "No website listed — scored from discovery data only",
};

export const EXTRACTOR_LABEL: Record<string, string> = {
  rule: "Rule match",
  llm: "LLM, quote-verified",
  places: "Google Places",
  osm: "OpenStreetMap",
  whois: "WHOIS",
  http: "HTTP check",
};

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
