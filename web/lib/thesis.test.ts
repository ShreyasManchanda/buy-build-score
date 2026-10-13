import { describe, expect, it } from "vitest";
import { mapHeaders, parseThesis, sniffCsv } from "./thesis";

describe("parseThesis", () => {
  it("splits industry and location", () => {
    expect(parseThesis("HVAC companies near Columbus, OH")).toEqual({ industry: "HVAC", location: "Columbus, OH" });
  });
  it("handles radius in miles and drops age qualifiers", () => {
    expect(parseThesis("landscaping cos in Austin, TX within 25 miles around 20 yrs old")).toEqual({
      industry: "landscaping",
      location: "Austin, TX",
      radiusKm: 40,
    });
  });
  it("industry only", () => {
    expect(parseThesis("family-owned plumbing")).toEqual({ industry: "plumbing" });
  });
});

describe("csv headers", () => {
  it("maps SaaSquatch export headers like the API", () => {
    const { headers, rows } = sniffCsv('﻿Company Name,"Website",Phone Number,City,State,Zip Code,Industry\na,b,c,d,e,f,g\n');
    expect(rows).toBe(1);
    const { mapping, unmapped } = mapHeaders(headers);
    expect(mapping).toMatchObject({
      name: "Company Name",
      website: "Website",
      phone: "Phone Number",
      city: "City",
      region: "State",
      postcode: "Zip Code",
      industry: "Industry",
    });
    expect(unmapped).toEqual([]);
  });
});
