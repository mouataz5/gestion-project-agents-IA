import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AutoRefresh } from "@/components/auto-refresh";
import {
  BackendError,
  Card,
  DefinitionList,
  EmptyState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { ACTIVE_RUN_STATUSES, type RunDetail, type SystemInfo } from "@/lib/api/types";
import { formatDateTime, formatDuration, humanize } from "@/lib/format";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Run detail" };

const COUNTERS = [
  ["jobs_discovered", "Jobs discovered"],
  ["jobs_processed", "Jobs processed"],
  ["jobs_qualified", "Jobs qualified"],
  ["cv_generated", "CVs generated"],
  ["applications_prepared", "Applications prepared"],
  ["applications_submitted", "Applications submitted"],
] as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function Json({ value }: { value: unknown }) {
  return (
    <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 font-mono text-xs dark:bg-slate-950">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default async function RunDetailPage(props: PageProps<"/runs/[id]">) {
  const { id } = await props.params;
  if (!UUID.test(id)) notFound();

  const [runResult, infoResult] = await Promise.all([
    backendGet<RunDetail>(`/runs/${id}`),
    backendGet<SystemInfo>("/system/info"),
  ]);
  if (!runResult.ok) {
    if (runResult.status === 404) notFound();
    return (
      <>
        <PageHeader title="Run detail" />
        <BackendError message={runResult.message} />
      </>
    );
  }
  const run = runResult.data;
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";
  const active = ACTIVE_RUN_STATUSES.includes(run.status);

  return (
    <>
      <PageHeader
        title={`${humanize(run.run_type)} run`}
        description={run.id}
        action={
          <div className="flex items-center gap-3">
            <AutoRefresh active={active} />
            <span data-testid="run-status">
              <StatusBadge status={run.status} />
            </span>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Overview" className="lg:col-span-2">
          <DefinitionList
            items={[
              ["Trigger", humanize(run.trigger)],
              [
                "Task id",
                <span key="task" className="font-mono text-xs">
                  {run.task_id ?? "—"}
                </span>,
              ],
              ["Created", formatDateTime(run.created_at, timeZone)],
              ["Started", formatDateTime(run.started_at, timeZone)],
              ["Finished", formatDateTime(run.finished_at, timeZone)],
              ["Duration", formatDuration(run.duration_seconds)],
            ]}
          />
        </Card>

        <Card title="Counters">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            {COUNTERS.map(([key, label]) => (
              <div key={key}>
                <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
                <dd className="text-lg font-semibold tabular-nums">{run[key]}</dd>
              </div>
            ))}
          </dl>
        </Card>

        <Card title={`Event timeline (${run.events.length})`} className="lg:col-span-3">
          {run.events.length === 0 ? (
            <EmptyState>
              {active ? "Waiting for the worker to pick up the run…" : "No events recorded."}
            </EmptyState>
          ) : (
            <ol className="space-y-3" data-testid="run-events">
              {run.events.map((event) => (
                <li key={event.id} className="flex gap-3 text-sm">
                  <span className="w-40 shrink-0 font-mono text-xs text-slate-500 dark:text-slate-400">
                    {formatDateTime(event.created_at, timeZone)}
                  </span>
                  <StatusBadge status={event.level} />
                  <div className="min-w-0">
                    <p className="font-medium">{event.message}</p>
                    <p className="font-mono text-xs text-slate-500 dark:text-slate-400">
                      {event.stage}
                    </p>
                    {Object.keys(event.data).length > 0 && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-xs text-slate-500">data</summary>
                        <Json value={event.data} />
                      </details>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>

        {run.errors.length > 0 && (
          <Card title={`Errors (${run.error_count})`} className="lg:col-span-3">
            <ul className="space-y-2 text-sm">
              {run.errors.map((error, index) => (
                <li
                  key={index}
                  className="rounded-lg border border-rose-200 p-3 dark:border-rose-500/30"
                >
                  <p className="font-medium text-rose-700 dark:text-rose-300">
                    {error.type}: {error.message}
                  </p>
                  <p className="text-xs text-slate-500">
                    {error.stage} · {formatDateTime(error.at, timeZone)}
                  </p>
                </li>
              ))}
            </ul>
          </Card>
        )}

        <Card title="Summary" className="lg:col-span-2">
          <Json value={run.summary} />
        </Card>
        <Card title="Parameters">
          <Json value={run.parameters} />
        </Card>
      </div>

      <p className="mt-6 text-sm">
        <Link href="/runs" className="text-indigo-600 hover:underline dark:text-indigo-400">
          ← All runs
        </Link>
      </p>
    </>
  );
}
