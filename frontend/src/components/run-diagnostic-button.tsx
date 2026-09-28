"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { ApiErrorResponse, RunCreated } from "@/lib/api/types";

/** Starts a system self-test run on a worker, then opens the run's live timeline. */
export function RunDiagnosticButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/backend/runs/diagnostic", { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setError(body?.error?.message ?? `Request failed (HTTP ${response.status})`);
        router.refresh(); // a failed enqueue is recorded as a FAILED run
        return;
      }
      const run = (await response.json()) as RunCreated;
      router.push(`/runs/${run.run_id}`);
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={start}
        disabled={pending}
        className="rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-wait disabled:opacity-60"
      >
        {pending ? "Starting…" : "Run system diagnostic"}
      </button>
      {error && (
        <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
    </div>
  );
}
