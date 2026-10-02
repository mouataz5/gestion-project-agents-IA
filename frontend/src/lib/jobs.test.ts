import { describe, expect, it } from "vitest";

import {
  DEFAULT_JOB_FILTERS,
  displayCompany,
  displayTitle,
  formatSalary,
  hostOf,
  importErrorMessage,
  jobsApiParams,
  jobsHref,
  parseJobFilters,
  postingDateLabel,
  postingDateTone,
  tabLabel,
  windowLabel,
} from "./jobs";

const NOW = new Date("2026-10-02T08:00:00Z");

describe("job filters", () => {
  it("defaults to the posting window", () => {
    expect(parseJobFilters({})).toEqual(DEFAULT_JOB_FILTERS);
    expect(jobsApiParams(DEFAULT_JOB_FILTERS, 25)).toEqual({
      window: "in_window",
      date_status: undefined,
      source: undefined,
      country: undefined,
      q: undefined,
      include_duplicates: undefined,
      limit: 25,
      offset: undefined,
    });
  });

  it("reads and validates the URL parameters", () => {
    const filters = parseJobFilters({
      tab: "unknown",
      source: "mock_feed",
      country: "fr",
      q: "  computer vision ",
      duplicates: "1",
      offset: ["25", "50"],
    });

    expect(filters).toEqual({
      tab: "unknown",
      source: "mock_feed",
      country: "FR",
      q: "computer vision",
      duplicates: true,
      offset: 25,
    });
    expect(jobsApiParams(filters, 25)).toMatchObject({
      window: "all",
      date_status: "UNKNOWN",
      include_duplicates: "true",
      offset: 25,
    });
  });

  it.each([
    [{ tab: "everything" }, { tab: "recent" }],
    [{ source: "../etc" }, { source: undefined }],
    [{ country: "France" }, { country: undefined }],
    [{ offset: "-10" }, { offset: 0 }],
    [{ offset: "abc" }, { offset: 0 }],
    [{ q: "   " }, { q: undefined }],
  ])("ignores malformed values %o", (params, expected) => {
    expect(parseJobFilters(params)).toMatchObject(expected);
  });

  it("builds short links that round-trip", () => {
    expect(jobsHref({})).toBe("/jobs");
    expect(jobsHref(DEFAULT_JOB_FILTERS)).toBe("/jobs");
    const href = jobsHref({ tab: "all", country: "DE", q: "ml ops", duplicates: true, offset: 50 });
    expect(href).toBe("/jobs?tab=all&country=DE&q=ml+ops&duplicates=1&offset=50");
    const params = Object.fromEntries(new URL(href, "http://x").searchParams);
    expect(parseJobFilters(params)).toEqual({
      tab: "all",
      source: undefined,
      country: "DE",
      q: "ml ops",
      duplicates: true,
      offset: 50,
    });
  });

  it("labels the tabs with the configured window", () => {
    expect(tabLabel("recent", 24)).toBe("Last 24 h");
    expect(tabLabel("all", 24)).toBe("All jobs");
    expect(tabLabel("unknown", 24)).toBe("Date unknown");
  });
});

describe("posting dates", () => {
  it("says how the date is known", () => {
    expect(
      postingDateLabel({ posted_at: "2026-10-02T05:00:00Z", posting_date_status: "KNOWN" }, NOW),
    ).toBe("Posted 3 h ago");
    expect(
      postingDateLabel(
        { posted_at: "2026-09-30T08:00:00Z", posting_date_status: "ESTIMATED" },
        NOW,
      ),
    ).toBe("≈ 2 d ago (estimated)");
    expect(postingDateLabel({ posted_at: null, posting_date_status: "UNKNOWN" }, NOW)).toBe(
      "Date unknown",
    );
  });

  it("uses distinct tones", () => {
    expect(postingDateTone("KNOWN")).toBe("success");
    expect(postingDateTone("ESTIMATED")).toBe("warning");
    expect(postingDateTone("UNKNOWN")).toBe("neutral");
    expect(windowLabel("IN_WINDOW", 24)).toBe("In the last 24 h");
    expect(windowLabel("OUT_OF_WINDOW", 48)).toBe("Older than 48 h");
    expect(windowLabel("UNKNOWN_DATE", 24)).toBe("Date unknown");
  });
});

describe("job fields", () => {
  const salary = { salary_currency: "EUR", salary_period: "year" };

  it.each([
    [{ salary_min: 65000, salary_max: 80000, ...salary }, "65,000–80,000 EUR / year"],
    [{ salary_min: 70000, salary_max: 70000, ...salary }, "70,000 EUR / year"],
    [{ salary_min: 50000, salary_max: null, ...salary }, "from 50,000 EUR / year"],
    [
      { salary_min: null, salary_max: 90000, salary_currency: null, salary_period: null },
      "up to 90,000",
    ],
    [{ salary_min: null, salary_max: null, ...salary }, null],
  ])("formats salary %o", (job, expected) => {
    expect(formatSalary(job)).toBe(expected);
  });

  it("never invents a title or a company for imported links", () => {
    expect(displayTitle("")).toBe("Untitled job");
    expect(displayTitle("AI Engineer")).toBe("AI Engineer");
    expect(displayCompany("  ")).toBe("Unknown company");
  });

  it("shows the host of a job URL", () => {
    expect(hostOf("https://www.linkedin.com/jobs/view/1")).toBe("linkedin.com");
    expect(hostOf("not a url")).toBeNull();
    expect(hostOf(null)).toBeNull();
  });

  it("explains import errors", () => {
    expect(importErrorMessage("unsafe_url", "x")).toMatch(/public http\(s\)/);
    expect(importErrorMessage("conflict", "Fallback")).toBe("Fallback");
    expect(importErrorMessage(undefined, "Fallback")).toBe("Fallback");
  });
});
