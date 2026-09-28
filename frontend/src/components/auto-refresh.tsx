"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-renders the current server page periodically while `active` (e.g. a run in progress). */
export function AutoRefresh({
  active,
  intervalMs = 1500,
}: {
  active: boolean;
  intervalMs?: number;
}) {
  const router = useRouter();

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [active, intervalMs, router]);

  return active ? (
    <span className="text-xs text-slate-500 dark:text-slate-400" aria-live="polite">
      Updating live…
    </span>
  ) : null;
}
