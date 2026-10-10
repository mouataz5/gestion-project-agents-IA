import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AtsScoreBadge } from "@/components/ats-score";
import { CvStructureView } from "@/components/cv-view";
import { Notice } from "@/components/form";
import { BackendError, Badge, Card, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import type { LedgerEntry, SystemInfo, TailoredCvDetail } from "@/lib/api/types";
import {
  STALE_NOTICE,
  ledgerByPath,
  originHelp,
  originLabel,
  originTone,
  stopReasonLabel,
} from "@/lib/ats";
import { formatDateTime } from "@/lib/format";
import { displayCompany, displayTitle } from "@/lib/jobs";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Tailored CV" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Where a text comes from: its origin and the master CV facts it cites. */
function SourceLine({ entry }: { entry: LedgerEntry }) {
  const reworded = entry.origin === "REWRITTEN" || entry.origin === "RETITLED";
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5" data-testid="source-line">
      <span title={originHelp(entry.origin)}>
        <Badge tone={originTone(entry.origin)}>{originLabel(entry.origin)}</Badge>
      </span>
      {entry.sources.map((source) => (
        <span key={source.id} title={source.text} data-testid="source-badge">
          <Badge tone="neutral">{source.label}</Badge>
        </span>
      ))}
      {reworded && entry.sources.length > 0 && (
        <details className="w-full text-xs text-slate-500 dark:text-slate-400">
          <summary className="cursor-pointer">Master CV text</summary>
          <ul className="mt-1 space-y-1">
            {entry.sources.map((source) => (
              <li
                key={source.id}
                className="border-l-2 border-slate-300 pl-2 dark:border-slate-600"
              >
                {source.text}
              </li>
            ))}
          </ul>
        </details>
      )}
    </span>
  );
}

export default async function TailoredCvPage(props: PageProps<"/cv/tailored/[id]">) {
  const { id } = await props.params;
  if (!UUID.test(id)) notFound();
  const [cvResult, infoResult] = await Promise.all([
    backendGet<TailoredCvDetail>(`/candidate/tailored-cvs/${id}`),
    backendGet<SystemInfo>("/system/info"),
  ]);
  if (!cvResult.ok) {
    if (cvResult.status === 404) notFound();
    return (
      <>
        <PageHeader title="Tailored CV" />
        <BackendError message={cvResult.message} />
      </>
    );
  }
  const cv = cvResult.data;
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";
  const target = infoResult.ok ? infoResult.data.config.ats_target_score : 95;
  const ledger = ledgerByPath(cv.ledger);
  const tailoring = cv.tailoring;
  const annotate = (path: string) => {
    const entry = ledger.get(path);
    const generated = path === "summary" || path.includes(".bullets.");
    if (!entry || (!generated && entry.origin !== "RETITLED")) return null;
    return <SourceLine entry={entry} />;
  };
  const skills = cv.ledger.filter((entry) => entry.path.startsWith("skills."));

  return (
    <>
      <div className="mb-2 flex flex-wrap gap-4 text-sm">
        <Link href="/cv" className="text-slate-500 hover:underline dark:text-slate-400">
          ← CV
        </Link>
        {cv.job_id && (
          <Link
            href={`/jobs/${cv.job_id}`}
            className="text-slate-500 hover:underline dark:text-slate-400"
          >
            ← Job
          </Link>
        )}
      </div>
      <PageHeader
        title={`Tailored CV · ${displayTitle(cv.job_title ?? "Untitled job")}`}
        description={`${displayCompany(cv.company ?? "")} · version ${cv.version} · ${formatDateTime(cv.created_at, timeZone)}`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            {cv.ats_score !== null && (
              <AtsScoreBadge
                score={cv.ats_score}
                target={target}
                ceiling={tailoring?.ceiling_score}
                size="lg"
              />
            )}
            <StatusBadge
              status={cv.status}
              label={cv.status === "GENERATED" ? "Current" : undefined}
            />
          </div>
        }
      />

      <div className="mb-6 space-y-3">
        {cv.stale && <Notice tone="warning">{STALE_NOTICE}</Notice>}
        {tailoring?.is_mock && (
          <Notice tone="info">
            Made by the offline mock tailoring: no language model wrote this CV, and every text is
            taken from your master CV.
          </Notice>
        )}
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Every summary and bullet below shows the facts of your master CV it comes from. Employers,
          titles, dates, education, certifications and languages are copied unchanged.
          {tailoring && (
            <>
              {" "}
              Target {tailoring.target_score} (a target, not a promise), reachable{" "}
              {tailoring.ceiling_score?.toFixed(1) ?? "—"}
              {tailoring.stop_reason ? ` · ${stopReasonLabel(tailoring.stop_reason)}` : ""} —{" "}
              {cv.job_id && (
                <Link href={`/jobs/${cv.job_id}`} className="underline">
                  score breakdown on the job page
                </Link>
              )}
            </>
          )}
        </p>
      </div>

      <CvStructureView structure={cv.structure} annotate={annotate} />

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Skills and their evidence">
          {skills.length === 0 ? (
            <EmptyState>No skills section.</EmptyState>
          ) : (
            <ul className="space-y-2 text-sm" data-testid="skill-evidence">
              {skills.map((entry) => {
                const index = Number(entry.path.split(".")[1]);
                const skill = cv.structure.skills[index];
                return (
                  <li key={entry.path} className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{skill?.name ?? entry.path}</span>
                    {entry.sources.length === 0 ? (
                      <span className="text-xs text-slate-500">your skills section</span>
                    ) : (
                      entry.sources.map((source) => (
                        <span key={source.id} title={source.text}>
                          <Badge tone="neutral">{source.label}</Badge>
                        </span>
                      ))
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title={`Not used in this version (${cv.unused_sources.length})`}>
          {cv.unused_sources.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Every fact of your master CV is used.
            </p>
          ) : (
            <ul className="space-y-2 text-sm" data-testid="unused-sources">
              {cv.unused_sources.map((source) => (
                <li key={source.id}>
                  <Badge tone="neutral">{source.label}</Badge>{" "}
                  <span className="text-slate-600 dark:text-slate-300">{source.text}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title={`Rewrites reverted by the guard (${cv.repairs.length})`}
          className="lg:col-span-2"
        >
          {cv.repairs.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No rewrite broke the truthfulness rules.
            </p>
          ) : (
            <ul className="space-y-3 text-sm" data-testid="repairs">
              {cv.repairs.map((repair, index) => (
                <li key={`${repair.path}-${index}`}>
                  <p className="text-slate-500 line-through dark:text-slate-400">
                    {repair.rejected_text}
                  </p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {repair.violations.map((violation, position) => (
                      <li key={position}>
                        <Badge tone="warning">
                          {violation.code.toLowerCase().replaceAll("_", " ")}: {violation.detail}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <details className="mt-6 rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
        <summary className="cursor-pointer font-medium">Plain text</summary>
        <pre className="mt-3 max-h-96 overflow-auto font-mono text-xs whitespace-pre-wrap">
          {cv.extracted_text}
        </pre>
      </details>
    </>
  );
}
