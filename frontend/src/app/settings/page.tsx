import type { Metadata } from "next";

import { BackendError, Badge, Card, DefinitionList, PageHeader } from "@/components/ui";
import type { SystemInfo } from "@/lib/api/types";
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
            ]}
          />
        </Card>

        <Card title="Pipeline">
          <DefinitionList
            items={[
              ["JOB_LOOKBACK_HOURS", String(config.job_lookback_hours)],
              ["ATS_TARGET_SCORE", String(config.ats_target_score)],
              ["ATS_MAX_ITERATIONS", String(config.ats_max_iterations)],
              ["DAILY_RUN_TIME", config.daily_run_time],
              ["TIMEZONE", config.timezone],
              ["SCHEDULER_ENABLED", config.scheduler_enabled ? "true" : "false"],
              ["LLM_PROVIDER", config.llm_provider],
              ["Model", config.llm_model],
              [
                "NOTIFICATION_CHANNELS",
                config.notification_channels.length
                  ? config.notification_channels.join(", ")
                  : "none",
              ],
            ]}
          />
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
