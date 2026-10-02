import type { Metadata } from "next";
import Link from "next/link";

import { HealthGrid } from "@/components/health-grid";
import { RunDiagnosticButton, RunDiscoveryButton } from "@/components/start-run-button";
import { RunsTable } from "@/components/runs-table";
import {
  BackendError,
  Badge,
  Card,
  DefinitionList,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import type { JobStats, RunPage, SystemInfo, SystemStatus } from "@/lib/api/types";
import { formatDateTime, type Tone } from "@/lib/format";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Dashboard" };

const PHASE_TONES: Record<string, Tone> = {
  done: "success",
  in_progress: "info",
  planned: "neutral",
};
const PHASE_LABELS: Record<string, string> = {
  done: "Done",
  in_progress: "In progress",
  planned: "Planned",
};

function DiscoverySummary({ stats, timeZone }: { stats: JobStats; timeZone: string }) {
  const hours = stats.window.lookback_hours;
  const tiles: Array<[string, number, string]> = [
    ["Found today", stats.found_today, "/jobs?tab=all"],
    [`Posted in the last ${hours} h`, stats.in_window, "/jobs"],
    ["Date unknown", stats.unknown_date, "/jobs?tab=unknown"],
    ["Unique jobs", stats.total, "/jobs?tab=all"],
  ];
  const last = stats.last_discovery;
  return (
    <div className="flex flex-col gap-4" data-testid="discovery-summary">
      <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {tiles.map(([label, value, href]) => (
          <div key={label} className="rounded-lg bg-slate-50 px-4 py-3 dark:bg-slate-800/50">
            <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</dt>
            <dd className="mt-1 text-2xl font-semibold tabular-nums">
              <Link href={href} className="hover:text-indigo-600 dark:hover:text-indigo-400">
                {value}
              </Link>
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {last ? (
          <>
            Last discovery:{" "}
            <Link href={`/runs/${last.id}`} className="inline-flex items-center gap-2">
              <StatusBadge status={last.status} />
            </Link>{" "}
            {formatDateTime(last.finished_at ?? last.created_at, timeZone)} · {last.jobs_discovered}{" "}
            new job(s) · {stats.duplicates} duplicate listing(s) merged
          </>
        ) : (
          "No discovery has run yet. Import the example companies on the Companies page, then run a discovery."
        )}
      </p>
    </div>
  );
}

export default async function DashboardPage() {
  const [infoResult, statusResult, runsResult, jobStatsResult] = await Promise.all([
    backendGet<SystemInfo>("/system/info"),
    backendGet<SystemStatus>("/system/status"),
    backendGet<RunPage>("/runs", { limit: 5 }),
    backendGet<JobStats>("/jobs/stats"),
  ]);

  if (!infoResult.ok) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <BackendError message={infoResult.message} />
      </>
    );
  }
  const info = infoResult.data;
  const timeZone = info.config.timezone;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Services, safety switches, job discovery, pipeline configuration and automation runs."
        action={<RunDiagnosticButton />}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card
          title="System health"
          className="lg:col-span-2"
          action={statusResult.ok ? <StatusBadge status={statusResult.data.status} /> : undefined}
        >
          {statusResult.ok ? (
            <HealthGrid components={statusResult.data.components} />
          ) : (
            <BackendError message={statusResult.message} />
          )}
        </Card>

        <Card title="Safety">
          <DefinitionList
            items={[
              [
                "Mode",
                info.mock_mode ? (
                  <Badge tone="warning">Mock · no real sites</Badge>
                ) : (
                  <Badge tone="danger">Live — real job sites</Badge>
                ),
              ],
              [
                "Submission",
                info.auto_submit ? (
                  <Badge tone="danger">Auto-submit enabled</Badge>
                ) : (
                  <Badge tone="success">Approval required</Badge>
                ),
              ],
              [
                "API authentication",
                info.auth_enabled ? (
                  <Badge tone="success">Enabled</Badge>
                ) : (
                  <Badge tone="danger">Disabled</Badge>
                ),
              ],
              ["Configuration warnings", String(info.warnings.length)],
            ]}
          />
        </Card>

        <Card
          title="Job discovery"
          className="lg:col-span-3"
          action={<RunDiscoveryButton variant="secondary" />}
        >
          {jobStatsResult.ok ? (
            <DiscoverySummary stats={jobStatsResult.data} timeZone={timeZone} />
          ) : (
            <BackendError message={jobStatsResult.message} />
          )}
        </Card>

        <Card title="Pipeline configuration" className="lg:col-span-3">
          <DefinitionList
            items={[
              ["Posting window", `last ${info.config.job_lookback_hours} hours`],
              [
                "ATS optimisation",
                `target ${info.config.ats_target_score}/100 · max ${info.config.ats_max_iterations} iterations`,
              ],
              [
                "Daily schedule",
                `${info.config.daily_run_time} ${info.config.timezone}${info.config.scheduler_enabled ? "" : " (disabled)"}`,
              ],
              ["LLM", `${info.config.llm_provider} · ${info.config.llm_model}`],
            ]}
          />
        </Card>

        <Card
          title="Recent automation runs"
          className="lg:col-span-2"
          action={
            <Link
              href="/runs"
              className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              All runs →
            </Link>
          }
        >
          {runsResult.ok ? (
            <RunsTable runs={runsResult.data.items} timeZone={timeZone} />
          ) : (
            <BackendError message={runsResult.message} />
          )}
        </Card>

        <Card title="Roadmap">
          <ol className="space-y-2 text-sm" data-testid="roadmap">
            {info.phases.map((phase) => (
              <li key={phase.number} className="flex items-start justify-between gap-3">
                <span>
                  <span className="text-slate-400">{phase.number}.</span> {phase.name}
                </span>
                <Badge tone={PHASE_TONES[phase.status] ?? "neutral"}>
                  {PHASE_LABELS[phase.status] ?? phase.status}
                </Badge>
              </li>
            ))}
          </ol>
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            Application, interview and offer metrics appear on this dashboard as the analysis and
            application phases are delivered.
          </p>
        </Card>
      </div>
    </>
  );
}
