import { describe, expect, it } from "vitest";

import { runJobCount } from "./runs";

describe("run job counts", () => {
  const counters = { jobs_discovered: 14, jobs_processed: 9, cv_generated: 2 };

  it("counts the jobs each kind of run worked on", () => {
    expect(runJobCount({ run_type: "DISCOVERY", ...counters })).toBe(14);
    expect(runJobCount({ run_type: "ANALYSIS", ...counters })).toBe(9);
    expect(runJobCount({ run_type: "CV_GENERATION", ...counters })).toBe(2);
    expect(
      runJobCount({
        run_type: "DIAGNOSTIC",
        jobs_discovered: 0,
        jobs_processed: 0,
        cv_generated: 0,
      }),
    ).toBe(0);
  });
});
