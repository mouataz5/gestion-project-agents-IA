"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/form";
import { runOutcomeMessage } from "@/lib/analysis";
import {
  ACTIVE_RUN_STATUSES,
  type AnalysisRunRequest,
  type ApiErrorResponse,
  type RunCreated,
  type RunDetail,
} from "@/lib/api/types";

const POLL_MS = 1500;
const MAX_WAIT_MS = 5 * 60_000;

/**
 * Analyses one job now (``force`` re-analyses an unchanged job), waits for the run on the worker,
 * then refreshes the page so the new analysis is shown.
 */
export function AnalyseJobButton({ jobId, analysed }: { jobId: string; analysed: boolean }) {
  const router = useRouter();
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "warning"; text: string } | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function waitFor(id: string): Promise<RunDetail | null> {
    const deadline = Date.now() + MAX_WAIT_MS;
    while (mounted.current && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      const response = await fetch(`/api/backend/runs/${id}`, { cache: "no-store" });
      if (!response.ok) continue;
      const run = (await response.json()) as RunDetail;
      if (!ACTIVE_RUN_STATUSES.includes(run.status)) return run;
    }
    return null;
  }

  async function analyse() {
    setBusy(true);
    setMessage(null);
    setRunId(null);
    try {
      const body: AnalysisRunRequest = { job_ids: [jobId], force: analysed };
      const response = await fetch("/api/backend/runs/analysis", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const error = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setMessage({
          tone: "error",
          text: error?.error?.message ?? `Request failed (HTTP ${response.status})`,
        });
        return;
      }
      const created = (await response.json()) as RunCreated;
      setRunId(created.run_id);
      const run = await waitFor(created.run_id);
      if (!mounted.current) return;
      if (run === null) {
        setMessage({ tone: "warning", text: "The analysis is still running." });
        return;
      }
      const outcome = runOutcomeMessage(run);
      if (outcome)
        setMessage({ tone: run.status === "FAILED" ? "error" : "warning", text: outcome });
      router.refresh();
    } catch {
      setMessage({ tone: "error", text: "Could not reach the dashboard server." });
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <span className="inline-flex max-w-sm flex-col items-end gap-1 text-right">
      <Button
        variant={analysed ? "secondary" : "primary"}
        onClick={() => void analyse()}
        disabled={busy}
        className="disabled:cursor-wait"
      >
        {busy ? "Analysing…" : analysed ? "Re-analyse" : "Analyse this job"}
      </Button>
      {busy && runId && (
        <span className="text-xs text-slate-500 dark:text-slate-400" aria-live="polite">
          Running on the worker ·{" "}
          <Link href={`/runs/${runId}`} className="underline">
            view run
          </Link>
        </span>
      )}
      {message && (
        <span
          role="alert"
          className={`text-xs ${message.tone === "error" ? "text-rose-600 dark:text-rose-400" : "text-amber-700 dark:text-amber-300"}`}
        >
          {message.text}
          {runId && !busy && (
            <>
              {" "}
              <Link href={`/runs/${runId}`} className="underline">
                Open the run
              </Link>
            </>
          )}
        </span>
      )}
    </span>
  );
}
