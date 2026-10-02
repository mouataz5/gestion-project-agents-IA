"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/form";
import type { ApiErrorResponse } from "@/lib/api/types";

/** Queues a job for the candidate by hand (e.g. a job whose posting date is unknown). */
export function TrackJobButton({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function track() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/backend/jobs/${jobId}/track`, { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setError(body?.error?.message ?? `Request failed (HTTP ${response.status})`);
        return;
      }
      router.refresh();
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button onClick={() => void track()} disabled={busy}>
        {busy ? "Adding…" : "Track this job"}
      </Button>
      {error && (
        <span role="alert" className="text-xs text-rose-600 dark:text-rose-400">
          {error}
        </span>
      )}
    </span>
  );
}
