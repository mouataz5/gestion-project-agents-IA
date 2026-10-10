import type { Metadata } from "next";

import { BackendError, Badge, Card, DefinitionList, PageHeader } from "@/components/ui";
import type { SystemInfo } from "@/lib/api/types";
import { componentLabel } from "@/lib/ats";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const result = await backendGet<SystemInfo>("/system/info");
  if (!result.ok) {
    return (
      <>
        <PageHeader title="Settings" />
        <BackendError message={result.message} />
      </>
    );
  }
  const info = result.data;
  const config = info.config;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Effective configuration of the running backend. Secrets are never displayed."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Application">
          <DefinitionList
            items={[
              ["Name", info.name],
              ["Version", info.version],
              ["Environment", info.environment],
              ["API prefix", info.api_prefix],
              ["Mock mode", info.mock_mode ? "true" : "false"],
              ["Auto-submit", info.auto_submit ? "true" : "false"],
              ["Logging", `${config.log_level} · ${config.log_format}`],
              ["Storage", config.storage_backend],
              ["MAX_UPLOAD_MB", String(config.max_upload_mb)],
            ]}
          />
        </Card>

        <Card title="Pipeline">
          <DefinitionList
            items={[
              ["JOB_LOOKBACK_HOURS", String(config.job_lookback_hours)],
              ["DAILY_RUN_TIME", config.daily_run_time],
              ["TIMEZONE", config.timezone],
              ["SCHEDULER_ENABLED", config.scheduler_enabled ? "true" : "false"],
              [
                "NOTIFICATION_CHANNELS",
                config.notification_channels.length
                  ? config.notification_channels.join(", ")
                  : "none",
              ],
            ]}
          />
        </Card>

        <Card title="ATS engine">
          <DefinitionList
            items={[
              ["ATS_TARGET_SCORE", `${config.ats_target_score} (a target, not a promise)`],
              ["ATS_MAX_ITERATIONS", String(config.ats_max_iterations)],
              ["Scoring", config.ats_scoring_version],
              ["CV_GENERATION_MAX_JOBS_PER_RUN", String(config.cv_generation_max_jobs_per_run)],
              [
                "CV_GENERATION_INCLUDE_REVIEW",
                config.cv_generation_include_review ? "true" : "false (APPLY jobs only)",
              ],
            ]}
          />
          <div className="mt-4 text-sm">
            <div className="mb-1 text-slate-500 dark:text-slate-400">ATS_SCORE_WEIGHTS</div>
            <ul className="flex flex-wrap gap-1.5" data-testid="ats-weights">
              {Object.entries(config.ats_score_weights).map(([name, weight]) => (
                <li key={name}>
                  <Badge tone="neutral">
                    {componentLabel(name)} {weight}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            Tailored CVs only reorder, select and reword the facts of your confirmed master CV. The
            tailoring call sees those facts and the job&apos;s grounded requirements, never your
            name, contact details, employers or schools.
          </p>
        </Card>

        <Card title="Language model">
          <DefinitionList
            items={[
              [
                "In use",
                <span key="effective" data-testid="llm-effective">
                  {config.llm_effective_provider === "claude" ? (
                    <Badge tone="success">Claude</Badge>
                  ) : config.llm_effective_provider === "mock" ? (
                    <Badge tone="warning">Offline mock</Badge>
                  ) : (
                    <Badge tone="danger">Unavailable</Badge>
                  )}
                  {config.llm_effective_reason && (
                    <span className="mt-1 block text-xs font-normal text-slate-500 dark:text-slate-400">
                      {config.llm_effective_reason}
                    </span>
                  )}
                </span>,
              ],
              ["LLM_PROVIDER", config.llm_provider],
              ["CLAUDE_MODEL", config.llm_model],
              ["LLM_EFFORT", config.llm_effort],
              [
                "LLM_REFUSAL_FALLBACK",
                config.llm_refusal_fallback
                  ? "true (a declined request is retried on the fallback model)"
                  : "false",
              ],
              ["ANALYSIS_MAX_JOBS_PER_RUN", String(config.analysis_max_jobs_per_run)],
              ["ANTHROPIC_API_KEY", info.secrets.anthropic_api_key ? "configured" : "not set"],
            ]}
          />
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            Job postings and a minimal set of CV facts (skills, experience, languages, work
            authorization; never contact details or employer names) are sent to the provider.
            Prompts and answers are never logged.
          </p>
        </Card>

        <Card title="Secrets">
          <ul className="space-y-2 text-sm" data-testid="secrets-status">
            {Object.entries(info.secrets).map(([name, configured]) => (
              <li key={name} className="flex items-center justify-between gap-3">
                <span className="font-mono text-xs">{name.toUpperCase()}</span>
                <Badge tone={configured ? "success" : "neutral"}>
                  {configured ? "configured" : "not set"}
                </Badge>
              </li>
            ))}
          </ul>
        </Card>

        <Card title={`Warnings (${info.warnings.length})`}>
          {info.warnings.length === 0 ? (
            <p className="text-sm text-slate-500">No configuration warnings.</p>
          ) : (
            <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-300">
              {info.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            Change settings in the repository-root <code className="font-mono">.env</code> file and
            restart the services. Every setting is documented in{" "}
            <code className="font-mono">.env.example</code>.
          </p>
        </Card>
      </div>
    </>
  );
}
