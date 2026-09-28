"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/form";
import type { ApiErrorResponse, CvVersionDetail } from "@/lib/api/types";

/** Copies a confirmed version into a new editable draft (the confirmed one stays active). */
export function CvReviseButton({ versionId }: { versionId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function revise() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/backend/candidate/master-cv/${versionId}/revise`, {
        method: "POST",
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setError(body?.error?.message ?? `Request failed (HTTP ${response.status})`);
        return;
      }
      const revision = (await response.json()) as CvVersionDetail;
      router.push(`/cv?version=${revision.id}`);
      router.refresh();
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button variant="secondary" onClick={() => void revise()} disabled={busy}>
        {busy ? "Creating draft…" : "Revise (new draft)"}
      </Button>
      {error && (
        <span role="alert" className="text-xs text-rose-600">
          {error}
        </span>
      )}
    </span>
  );
}
