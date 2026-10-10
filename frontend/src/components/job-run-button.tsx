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

const KINDS = {
  analysis: {
    path: "/api/backend/runs/analysis",
    noun: "analysis",
    first: "Analyse this job",
    again: "Re-analyse",
    busy: "Analysing…",
  },
  tailoring: {
    path: "/api/backend/runs/cv-generation",
    noun: "CV generation",
    first: "Tailor CV",
    again: "Re-tailor",
    busy: "Tailoring…",
  },
} as const;

const POLL_MS = 1500;
const MAX_WAIT_MS = 5 * 60_000;

/**
 * Runs one job through a pipeline step now (``force`` redoes it when it was already done), waits
 * for the run on the worker, then refreshes the page so the new result is shown.
 */
export function JobRunButton({
  jobId,
  kind,
  done,
}: {
  jobId: string;
  kind: keyof typeof KINDS;
  done: boolean;
}) {
  const labels = KINDS[kind];
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

  async function start() {
    setBusy(true);
    setMessage(null);
    setRunId(null);
    try {
      // The analysis and CV generation requests have the same shape.
      const body: AnalysisRunRequest = { job_ids: [jobId], force: done };
      const response = await fetch(labels.path, {
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
        setMessage({ tone: "warning", text: `The ${labels.noun} is still running.` });
        return;
      }
      const outcome = runOutcomeMessage(run, labels.noun);
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
        variant={done ? "secondary" : "primary"}
        onClick={() => void start()}
        disabled={busy}
        className="disabled:cursor-wait"
      >
        {busy ? labels.busy : done ? labels.again : labels.first}
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

export function AnalyseJobButton({ jobId, analysed }: { jobId: string; analysed: boolean }) {
  return <JobRunButton jobId={jobId} kind="analysis" done={analysed} />;
}

export function TailorCvButton({ jobId, tailored }: { jobId: string; tailored: boolean }) {
  return <JobRunButton jobId={jobId} kind="tailoring" done={tailored} />;
}
