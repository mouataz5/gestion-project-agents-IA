"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { buttonClass } from "@/components/form";
import type { ApiErrorResponse, RunCreated } from "@/lib/api/types";

const RUNS = {
  diagnostic: { path: "/api/backend/runs/diagnostic", label: "Run system diagnostic" },
  discovery: { path: "/api/backend/runs/discovery", label: "Run job discovery" },
} as const;

/** Starts a recorded automation run on a worker, then opens the run's live timeline. */
export function StartRunButton({
  run,
  variant = "primary",
}: {
  run: keyof typeof RUNS;
  variant?: "primary" | "secondary";
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(RUNS[run].path, { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setError(body?.error?.message ?? `Request failed (HTTP ${response.status})`);
        router.refresh(); // a failed enqueue is recorded as a FAILED run
        return;
      }
      const created = (await response.json()) as RunCreated;
      router.push(`/runs/${created.run_id}`);
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
        className={`${buttonClass(variant)} disabled:cursor-wait`}
      >
        {pending ? "Starting…" : RUNS[run].label}
      </button>
      {error && (
        <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
    </div>
  );
}

export function RunDiagnosticButton() {
  return <StartRunButton run="diagnostic" />;
}

export function RunDiscoveryButton({ variant }: { variant?: "primary" | "secondary" }) {
  return <StartRunButton run="discovery" variant={variant} />;
}
