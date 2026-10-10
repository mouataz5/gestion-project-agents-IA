import type { RunSummary } from "@/lib/api/types";

/** The jobs a run worked on: found by a discovery, analysed by an analysis, CVs tailored. */
export function runJobCount(
  run: Pick<RunSummary, "run_type" | "jobs_discovered" | "jobs_processed" | "cv_generated">,
): number {
  if (run.run_type === "ANALYSIS") return run.jobs_processed;
  if (run.run_type === "CV_GENERATION") return run.cv_generated;
  return run.jobs_discovered;
}
