import { describe, expect, it } from "vitest";

import { NAV_ITEMS, implementedPhaseNumbers, isActivePath, navigationFor } from "./nav";

describe("navigation", () => {
  it("lists every dashboard page from the specification in order", () => {
    expect(NAV_ITEMS.map((item) => item.href)).toEqual([
      "/dashboard",
      "/jobs",
      "/applications",
      "/candidate",
      "/cv",
      "/companies",
      "/settings",
      "/runs",
    ]);
  });

  it("enables only pages whose phase is implemented", () => {
    const items = navigationFor(new Set([1]));
    const enabled = items.filter((item) => item.enabled).map((item) => item.href);

    expect(enabled).toEqual(["/dashboard", "/settings", "/runs"]);
    expect(items.find((item) => item.href === "/jobs")).toMatchObject({ enabled: false, phase: 3 });
  });

  it("derives implemented phases from the roadmap", () => {
    const phases = [
      { number: 1, name: "Foundation", status: "done", summary: "" },
      { number: 2, name: "Candidate", status: "in_progress", summary: "" },
      { number: 3, name: "Jobs", status: "planned", summary: "" },
    ];
    expect([...implementedPhaseNumbers(phases)]).toEqual([1]);
  });

  it("falls back to the foundation phase when the roadmap is unavailable", () => {
    expect([...implementedPhaseNumbers(undefined)]).toEqual([1]);
  });

  it.each([
    ["/runs", "/runs", true],
    ["/runs/3f2a", "/runs", true],
    ["/runs-archive", "/runs", false],
    ["/dashboard", "/runs", false],
  ])("isActivePath(%s, %s) is %s", (pathname, href, expected) => {
    expect(isActivePath(pathname, href)).toBe(expected);
  });
});
