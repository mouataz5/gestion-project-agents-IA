import { describe, expect, it } from "vitest";

import { formatDateTime, formatDuration, formatRelative, humanize, statusTone } from "./format";

describe("formatDuration", () => {
  it.each([
    [null, "—"],
    [undefined, "—"],
    [0.0421, "42 ms"],
    [5.26, "5.3 s"],
    [125, "2 min 5 s"],
    [3725, "1 h 2 min"],
  ])("formats %s seconds as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});

describe("formatDateTime", () => {
  it("formats ISO timestamps in the requested time zone", () => {
    expect(formatDateTime("2026-09-28T07:05:09Z", "Africa/Tunis")).toBe("2026-09-28 08:05:09");
    expect(formatDateTime("2026-09-28T07:05:09Z", "UTC")).toBe("2026-09-28 07:05:09");
  });

  it("handles missing and invalid values", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-28T12:00:00Z");

  it.each([
    ["2026-09-28T11:59:58Z", "just now"],
    ["2026-09-28T11:59:30Z", "30 s ago"],
    ["2026-09-28T11:45:00Z", "15 min ago"],
    ["2026-09-28T09:00:00Z", "3 h ago"],
    ["2026-09-25T12:00:00Z", "3 d ago"],
    ["2026-09-28T12:10:00Z", "in 10 min"],
  ])("describes %s as %s", (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });
});

describe("statusTone", () => {
  it.each([
    ["ok", "success"],
    ["SUCCEEDED", "success"],
    ["degraded", "warning"],
    ["PARTIAL_SUCCESS", "warning"],
    ["WARNING", "warning"],
    ["down", "danger"],
    ["FAILED", "danger"],
    ["ERROR", "danger"],
    ["RUNNING", "info"],
    ["PENDING", "info"],
    ["CANCELLED", "neutral"],
    ["something-else", "neutral"],
  ])("maps %s to %s", (status, tone) => {
    expect(statusTone(status)).toBe(tone);
  });
});

describe("humanize", () => {
  it("turns enum-like values into readable labels", () => {
    expect(humanize("PARTIAL_SUCCESS")).toBe("Partial success");
    expect(humanize("diagnostic.database")).toBe("Diagnostic database");
    expect(humanize("ok")).toBe("Ok");
  });
});
