import Link from "next/link";

import type { RunSummary } from "@/lib/api/types";
import { formatDateTime, formatDuration, humanize } from "@/lib/format";
import { runJobCount } from "@/lib/runs";

import { EmptyState, StatusBadge } from "./ui";

export function RunsTable({ runs, timeZone }: { runs: RunSummary[]; timeZone: string }) {
  if (runs.length === 0) {
    return (
      <EmptyState>No automation runs yet. Start a system diagnostic to create one.</EmptyState>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
          <tr className="border-b border-slate-200 dark:border-slate-800">
            <th className="py-2 pr-4 font-medium">Run</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Trigger</th>
            <th className="py-2 pr-4 font-medium">Created</th>
            <th className="py-2 pr-4 font-medium">Duration</th>
            <th className="py-2 pr-4 text-right font-medium">Jobs</th>
            <th className="py-2 text-right font-medium">Errors</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr
              key={run.id}
              data-testid="run-row"
              className="border-b border-slate-100 last:border-0 dark:border-slate-800/60"
            >
              <td className="py-2.5 pr-4">
                <Link
                  href={`/runs/${run.id}`}
                  className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                >
                  {humanize(run.run_type)}
                </Link>
                <div className="font-mono text-xs text-slate-400">{run.id.slice(0, 8)}</div>
              </td>
              <td className="py-2.5 pr-4">
                <StatusBadge status={run.status} />
              </td>
              <td className="py-2.5 pr-4">{humanize(run.trigger)}</td>
              <td className="py-2.5 pr-4 whitespace-nowrap">
                {formatDateTime(run.created_at, timeZone)}
              </td>
              <td className="py-2.5 pr-4">{formatDuration(run.duration_seconds)}</td>
              <td className="py-2.5 pr-4 text-right tabular-nums">{runJobCount(run)}</td>
              <td className="py-2.5 text-right tabular-nums">{run.error_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
