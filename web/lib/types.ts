export type Tier = "A" | "B" | "C";
export type Dimension = "durability" | "succession" | "upside";
export type Preset = "searcher" | "sdr" | "caprae";
export type CrawlStatus = "ok" | "partial" | "blocked_robots" | "unreachable" | "no_site";
export type RunStatus = "queued" | "discovering" | "crawling" | "scoring" | "done" | "failed";

export interface Scores {
  durability: number;
  succession: number;
  upside: number;
  composite: number;
  tier: Tier;
  capped: "durability_floor" | "thin_data" | null;
}

export interface LeadOut {
  id: string;
  company_id: string;
  name: string;
  domain: string | null;
  website: string | null;
  city: string | null;
  region: string | null;
  phone: string | null;
  founded_year: number | null;
  owner_name: string | null;
  rating: number | null;
  review_count: number | null;
  scores: Scores;
  coverage: number;
  thin_data: boolean;
  top_evidence: string[];
  email_status: "valid_mx" | "no_mx" | "invalid" | "none" | null;
  phone_valid: boolean | null;
  crawl_status: CrawlStatus | null;
  durability_mode: "full" | "site_only";
  lat: number | null;
  lng: number | null;
}

export interface EvidenceOut {
  dimension: Dimension;
  signal: string;
  label: string;
  value: string | null;
  points: number;
  max_points: number;
  confidence: number;
  source_url: string | null;
  snippet: string | null;
  extractor: "rule" | "llm" | "places" | "osm" | "whois" | "http";
}

export interface MissingSignal {
  dimension: Dimension;
  signal: string;
  label: string;
  max_points: number;
}

export interface LeadDetail extends LeadOut {
  evidence: EvidenceOut[];
  missing: MissingSignal[];
  address: string | null;
  postcode: string | null;
  email: string | null;
  owner_title: string | null;
  owner_source_url: string | null;
  services: string[];
  tech: string[];
  run_id: string;
  place_id: string | null;
  osm_id: string | null;
}

export interface RunCounts {
  discovered?: number;
  deduped?: number;
  chains_dropped?: number;
  crawled?: number;
  scored?: number;
  ok?: number;
  partial?: number;
  no_site?: number;
  unreachable?: number;
  blocked_robots?: number;
  failed?: number;
  llm_calls?: number;
  rejected?: number;
}

export interface RunOut {
  id: string;
  source: "thesis" | "csv" | "demo";
  query: {
    industry?: string;
    location?: string;
    radius_km?: number;
    max_results?: number;
    expand?: boolean;
    filename?: string;
    rows?: number;
    geo?: { lat: number; lng: number; display_name: string };
  };
  preset: Preset;
  status: RunStatus;
  mode: "osm" | "places" | "csv" | "demo";
  counts: RunCounts;
  warnings: { company: string | null; reason: string; upstream?: boolean }[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Weights {
  durability: number;
  succession: number;
  upside: number;
}

export interface ThesisIn {
  industry: string;
  location: string;
  radius_km: number;
  max_results: 20 | 40 | 60;
  expand: boolean;
  preset: Preset;
}

export interface Health {
  ok: boolean;
  db: boolean;
  mode: { places: boolean; llm: boolean; hubspot: boolean; pagespeed: boolean };
}
