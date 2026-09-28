import type { Metadata } from "next";
import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { RunDiagnosticButton } from "@/components/run-diagnostic-button";
import { RunsTable } from "@/components/runs-table";
import { BackendError, Card, PageHeader } from "@/components/ui";
import {
  ACTIVE_RUN_STATUSES,
  RUN_STATUSES,
  type RunPage,
  type RunStatus,
  type SystemInfo,
} from "@/lib/api/types";
import { humanize } from "@/lib/format";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Automation runs" };

const PAGE_SIZE = 20;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function pageHref(status: RunStatus | undefined, offset: number): string {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `/runs?${query}` : "/runs";
}

export default async function RunsPage(props: PageProps<"/runs">) {
  const searchParams = await props.searchParams;
  const requestedStatus = first(searchParams.status);
  const status = RUN_STATUSES.find((candidate) => candidate === requestedStatus);
  const offset = Math.max(0, Number.parseInt(first(searchParams.offset) ?? "0", 10) || 0);

  const [runsResult, infoResult] = await Promise.all([
    backendGet<RunPage>("/runs", { limit: PAGE_SIZE, offset, status }),
    backendGet<SystemInfo>("/system/info"),
  ]);
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";
  const hasActiveRuns =
    runsResult.ok && runsResult.data.items.some((run) => ACTIVE_RUN_STATUSES.includes(run.status));

  return (
    <>
      <PageHeader
        title="Automation runs"
        description="Every automation run with its counters, errors and event timeline."
        action={<RunDiagnosticButton />}
      />
      <Card
        action={<AutoRefresh active={hasActiveRuns} />}
        title={runsResult.ok ? `${runsResult.data.total} run(s)` : "Runs"}
      >
        <div className="mb-4 flex flex-wrap gap-2" aria-label="Filter by status">
          {[undefined, ...RUN_STATUSES].map((candidate) => {
            const selected = candidate === status;
            return (
              <Link
                key={candidate ?? "all"}
                href={pageHref(candidate, 0)}
                aria-current={selected ? "true" : undefined}
                className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
                  selected
                    ? "bg-indigo-600 text-white ring-indigo-600"
                    : "text-slate-600 ring-slate-300 hover:bg-slate-100 dark:text-slate-300 dark:ring-slate-700 dark:hover:bg-slate-800"
                }`}
              >
                {candidate ? humanize(candidate) : "All"}
              </Link>
            );
          })}
        </div>

        {runsResult.ok ? (
          <>
            <RunsTable runs={runsResult.data.items} timeZone={timeZone} />
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-slate-500 dark:text-slate-400">
                {runsResult.data.total === 0
                  ? "No runs"
                  : `Showing ${offset + 1}–${offset + runsResult.data.items.length} of ${runsResult.data.total}`}
              </span>
              <div className="flex gap-2">
                {offset > 0 && (
                  <Link
                    className="rounded-md px-3 py-1 ring-1 ring-slate-300 dark:ring-slate-700"
                    href={pageHref(status, Math.max(0, offset - PAGE_SIZE))}
                  >
                    Previous
                  </Link>
                )}
                {offset + PAGE_SIZE < runsResult.data.total && (
                  <Link
                    className="rounded-md px-3 py-1 ring-1 ring-slate-300 dark:ring-slate-700"
                    href={pageHref(status, offset + PAGE_SIZE)}
                  >
                    Next
                  </Link>
                )}
              </div>
            </div>
          </>
        ) : (
          <BackendError message={runsResult.message} />
        )}
      </Card>
    </>
  );
}
