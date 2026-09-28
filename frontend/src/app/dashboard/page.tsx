import type { Metadata } from "next";
import Link from "next/link";

import { HealthGrid } from "@/components/health-grid";
import { RunDiagnosticButton } from "@/components/run-diagnostic-button";
import { RunsTable } from "@/components/runs-table";
import {
  BackendError,
  Badge,
  Card,
  DefinitionList,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import type { RunPage, SystemInfo, SystemStatus } from "@/lib/api/types";
import type { Tone } from "@/lib/format";
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

export default async function DashboardPage() {
  const [infoResult, statusResult, runsResult] = await Promise.all([
    backendGet<SystemInfo>("/system/info"),
    backendGet<SystemStatus>("/system/status"),
    backendGet<RunPage>("/runs", { limit: 5 }),
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
        description="Foundation status: services, safety switches, pipeline configuration and automation runs."
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
                  <Badge tone="warning">Mock — fake jobs, mock ATS only</Badge>
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
            Job, application and interview metrics appear on this dashboard as the discovery and
            application phases are delivered.
          </p>
        </Card>
      </div>
    </>
  );
}
