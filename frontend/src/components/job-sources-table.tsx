import type { JobSource } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";

import { Badge, StatusBadge } from "./ui";

const POLICY_LABELS: Record<JobSource["policy"], string> = {
  api_only: "Official API only",
  allowed: "Allowed (robots.txt, rate limits)",
  manual_only: "Manual import only",
  disabled: "Disabled",
};

/** Source policy (crawler/sources.yaml) and whether each source runs in the current mode. */
export function JobSourcesTable({ sources, timeZone }: { sources: JobSource[]; timeZone: string }) {
  // Sources that run now first; the API order (priority) is kept otherwise.
  const ordered = [...sources].sort((a, b) => Number(b.runnable) - Number(a.runnable));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
          <tr className="border-b border-slate-200 dark:border-slate-800">
            <th className="py-2 pr-4 font-medium">Source</th>
            <th className="py-2 pr-4 font-medium">Policy</th>
            <th className="py-2 pr-4 font-medium">Runs now</th>
            <th className="py-2 font-medium">Last run</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((source) => (
            <tr
              key={source.key}
              data-testid="source-row"
              className="border-b border-slate-100 align-top last:border-0 dark:border-slate-800/60"
            >
              <td className="py-2.5 pr-4">
                <div className="font-medium">{source.name}</div>
                <div className="font-mono text-xs text-slate-400">
                  {source.key} · {humanize(source.kind)}
                  {source.is_mock ? " · mock" : ""}
                </div>
              </td>
              <td className="py-2.5 pr-4">
                <div>{POLICY_LABELS[source.policy]}</div>
                {source.notes && (
                  <div className="mt-0.5 max-w-md text-xs text-slate-500 dark:text-slate-400">
                    {source.notes}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-4">
                {source.runnable ? (
                  <Badge tone="success">Yes</Badge>
                ) : (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {source.skip_reason}
                  </span>
                )}
              </td>
              <td className="py-2.5 whitespace-nowrap">
                {source.last_status ? (
                  <div className="flex flex-col gap-1">
                    <StatusBadge status={source.last_status} />
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {formatDateTime(source.last_run_at, timeZone)}
                    </span>
                  </div>
                ) : (
                  <span className="text-xs text-slate-400">Never</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
