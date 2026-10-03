import type { RunSummary } from "@/lib/api/types";

/** The jobs a run worked on: found by a discovery, analysed by an analysis. */
export function runJobCount(
  run: Pick<RunSummary, "run_type" | "jobs_discovered" | "jobs_processed">,
): number {
  return run.run_type === "ANALYSIS" ? run.jobs_processed : run.jobs_discovered;
}
