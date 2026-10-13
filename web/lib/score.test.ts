import { describe, expect, it } from "vitest";
import { composite, presetWeights, rank, roundHalfUp, tierOf } from "./score";
import type { LeadOut } from "./types";

function lead(d: number, s: number, u: number, coverage = 0.9, apiComposite?: number): LeadOut {
  return {
    id: "x",
    company_id: "c",
    name: "Acme",
    domain: "acme.com",
    website: null,
    city: null,
    region: null,
    phone: null,
    founded_year: null,
    owner_name: null,
    rating: null,
    review_count: null,
    scores: { durability: d, succession: s, upside: u, composite: apiComposite ?? 0, tier: "C", capped: null },
    coverage,
    thin_data: coverage < 0.4,
    top_evidence: [],
    email_status: null,
    phone_valid: null,
    crawl_status: "ok",
    durability_mode: "site_only",
    lat: null,
    lng: null,
  };
}

describe("composite", () => {
  it("matches the API's composites for every preset (values computed by api/app/pipeline/score.py)", () => {
    // (d, s, u) -> {searcher, sdr, caprae} as returned by GET /runs/{id}/leads
    const cases: [number, number, number, number, number, number][] = [
      [80, 60, 40, 64, 52, 60],
      [89, 77, 77, 82, 80, 81],
      [26, 0, 18, 14, 18, 15],
      [89, 50, 41, 64, 54, 61],
      [100, 100, 100, 100, 100, 100],
      [0, 0, 0, 0, 0, 0],
    ];
    for (const [d, s, u, searcher, sdr, caprae] of cases) {
      expect(composite(d, s, u, presetWeights("searcher"))).toBe(searcher);
      expect(composite(d, s, u, presetWeights("sdr"))).toBe(sdr);
      expect(composite(d, s, u, presetWeights("caprae"))).toBe(caprae);
    }
  });

  it("rounds half up like the API, not to even", () => {
    expect(roundHalfUp(88.5)).toBe(89);
    expect(roundHalfUp(64.5)).toBe(65);
    expect(composite(1, 0, 0, { durability: 1, succession: 1, upside: 0 })).toBe(1);
  });

  it("is within ±1 of the API composite after any re-weighting", () => {
    const api = lead(89, 77, 77, 0.9, 82);
    expect(Math.abs(rank(api, presetWeights("searcher")).composite - api.scores.composite)).toBeLessThanOrEqual(1);
  });

  it("returns 0 when every weight is 0", () => {
    expect(composite(90, 90, 90, { durability: 0, succession: 0, upside: 0 })).toBe(0);
  });
});

describe("tier guardrails", () => {
  it("bands at 70 / 50", () => {
    expect(tierOf(70, 80, 0.9).tier).toBe("A");
    expect(tierOf(69, 80, 0.9).tier).toBe("B");
    expect(tierOf(50, 80, 0.9).tier).toBe("B");
    expect(tierOf(49, 80, 0.9).tier).toBe("C");
  });
  it("caps A at B on thin data or a weak durability floor", () => {
    expect(tierOf(85, 80, 0.39)).toEqual({ tier: "B", capped: "thin_data" });
    expect(tierOf(85, 29, 0.9)).toEqual({ tier: "B", capped: "durability_floor" });
    expect(tierOf(85, 30, 0.9)).toEqual({ tier: "A", capped: null });
  });
});

describe("rank", () => {
  it("re-ranks 500 leads well under 100 ms", () => {
    const leads = Array.from({ length: 500 }, (_, i) => lead(i % 101, (i * 7) % 101, (i * 13) % 101));
    const t = performance.now();
    for (let k = 0; k < 10; k++) {
      leads.map((l) => rank(l, presetWeights(k % 2 ? "sdr" : "searcher"))).sort((a, b) => b.composite - a.composite);
    }
    expect((performance.now() - t) / 10).toBeLessThan(100);
  });
});
