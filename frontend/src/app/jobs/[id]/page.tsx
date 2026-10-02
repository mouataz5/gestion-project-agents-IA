import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { Notice } from "@/components/form";
import { PostingDateBadge } from "@/components/jobs-table";
import { TrackJobButton } from "@/components/track-job-button";
import {
  BackendError,
  Badge,
  Card,
  DefinitionList,
  EmptyState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import type { JobDetail, SystemInfo } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import {
  displayCompany,
  displayTitle,
  formatSalary,
  hostOf,
  postingDateLabel,
  windowLabel,
} from "@/lib/jobs";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Job" };

const IMPORT_NOTICES: Record<string, string> = {
  created: "Job imported and added to the pipeline.",
  existing: "This job was already imported: its details were updated.",
  duplicate: "This job was already known from another source: the existing record is shown.",
};

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
    >
      {children} ↗
    </a>
  );
}

function Tags({ items, empty = "—" }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <span className="text-slate-400">{empty}</span>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item}
          className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {item}
        </span>
      ))}
    </span>
  );
}

export default async function JobDetailPage(props: PageProps<"/jobs/[id]">) {
  const [{ id }, searchParams] = await Promise.all([props.params, props.searchParams]);
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const [jobResult, infoResult] = await Promise.all([
    backendGet<JobDetail>(`/jobs/${id}`),
    backendGet<SystemInfo>("/system/info"),
  ]);
  if (!jobResult.ok) {
    if (jobResult.status === 404) notFound();
    return (
      <>
        <PageHeader title="Job" />
        <BackendError message={jobResult.message} />
      </>
    );
  }
  const job = jobResult.data;
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";
  const hours = infoResult.ok ? infoResult.data.config.job_lookback_hours : 24;
  const imported = Array.isArray(searchParams.imported)
    ? searchParams.imported[0]
    : searchParams.imported;
  const salary = formatSalary(job);
  const queued = job.applications.length > 0;

  return (
    <>
      <div className="mb-2 text-sm">
        <Link href="/jobs" className="text-slate-500 hover:underline dark:text-slate-400">
          ← Jobs
        </Link>
      </div>
      <PageHeader
        title={displayTitle(job.title)}
        description={[displayCompany(job.company), job.location].filter(Boolean).join(" · ")}
        action={
          <div className="flex flex-wrap items-start gap-3">
            {job.application_url && (
              <span className="pt-2 text-sm">
                <ExternalLink href={job.application_url}>
                  Open posting
                  {hostOf(job.application_url) ? ` on ${hostOf(job.application_url)}` : ""}
                </ExternalLink>
              </span>
            )}
            {!queued && !job.duplicate_of_id && <TrackJobButton jobId={job.id} />}
          </div>
        }
      />

      <div className="mb-6 space-y-3">
        {imported && IMPORT_NOTICES[imported] && (
          <Notice tone="success">{IMPORT_NOTICES[imported]}</Notice>
        )}
        {job.primary && (
          <Notice tone="info">
            This is a duplicate listing of{" "}
            <Link href={`/jobs/${job.primary.id}`} className="font-medium underline">
              {displayTitle(job.primary.title)} ({job.primary.source})
            </Link>
            : the primary record is the one that enters the pipeline.
          </Notice>
        )}
        {!queued && !job.duplicate_of_id && job.window_status === "UNKNOWN_DATE" && (
          <Notice tone="warning">
            The posting date is unknown, so this job is never counted as recent and is not queued
            automatically. Track it if you want it analysed.
          </Notice>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Overview" className="lg:col-span-2">
          <DefinitionList
            items={[
              ["Company", displayCompany(job.company)],
              ["Location", job.location ?? "—"],
              ["Country", job.country ? `${job.country} (${job.country_code})` : "—"],
              ["Workplace", humanize(job.remote_status)],
              ["Employment", humanize(job.employment_type)],
              ["Seniority", humanize(job.seniority)],
              ["Salary", salary ?? "Not published"],
              [
                "Source",
                <span key="source" className="font-mono text-xs">
                  {job.source}
                </span>,
              ],
              ["ATS", humanize(job.ats_type)],
              ["Discovered", formatDateTime(job.discovered_at, timeZone)],
            ]}
          />
        </Card>

        <Card title="Posting date">
          <div className="space-y-3 text-sm">
            <div>
              <PostingDateBadge job={job} hours={hours} />
            </div>
            <div>
              <div className="text-slate-500 dark:text-slate-400">Window</div>
              <div className="font-medium" data-testid="window-status">
                {windowLabel(job.window_status, hours)}
              </div>
            </div>
            {job.posted_at && (
              <div>
                <div className="text-slate-500 dark:text-slate-400">
                  {job.posting_date_status === "ESTIMATED" ? "Oldest plausible time" : "Posted at"}
                </div>
                <div className="font-medium">{formatDateTime(job.posted_at, timeZone)}</div>
              </div>
            )}
            {job.posting_date_basis && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Basis: {job.posting_date_basis}
              </p>
            )}
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {postingDateLabel(job)} · last seen {formatDateTime(job.last_seen_at, timeZone)}
            </p>
          </div>
        </Card>

        <Card title="Description" className="lg:col-span-2">
          {job.description ? (
            <div className="text-sm leading-6 whitespace-pre-line">{job.description}</div>
          ) : (
            <EmptyState>
              No description stored. Imported links are not fetched: open the posting to read it.
            </EmptyState>
          )}
        </Card>

        <Card title="Pipeline">
          {queued ? (
            <ul className="space-y-2 text-sm">
              {job.applications.map((application) => (
                <li key={application.id} className="flex items-center justify-between gap-2">
                  <StatusBadge status={application.status} />
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    since {formatDateTime(application.created_at, timeZone)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Not queued.{" "}
              {job.duplicate_of_id
                ? "Duplicate listings are never queued."
                : "Automatic queueing needs an AI/ML title, a target country and a posting date in the window."}
            </p>
          )}
          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            Analysis, visa classification and matching arrive in Phase 4.
          </p>
        </Card>

        <Card title="Requirements" className="lg:col-span-2">
          <DefinitionList
            items={[
              ["Required skills", <Tags key="required" items={job.required_skills} />],
              ["Preferred skills", <Tags key="preferred" items={job.preferred_skills} />],
              ["Languages", <Tags key="languages" items={job.languages} />],
              ["Education", job.education_requirements ?? "—"],
              ["Experience", job.experience_requirements ?? "—"],
              ["Visa", job.visa_information ?? "Not stated"],
              ["Relocation", job.relocation_information ?? "Not stated"],
            ]}
          />
          {job.responsibilities.length > 0 && (
            <div className="mt-4 text-sm">
              <div className="mb-1 text-slate-500 dark:text-slate-400">Responsibilities</div>
              <ul className="list-disc space-y-1 pl-5">
                {job.responsibilities.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card title="Other listings">
          {job.duplicates.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No other source listed this job.
            </p>
          ) : (
            <ul className="space-y-3 text-sm" data-testid="duplicate-listings">
              {job.duplicates.map((listing) => (
                <li key={listing.id}>
                  <div className="flex items-center gap-2">
                    <Badge tone="neutral">{listing.source}</Badge>
                    <Link href={`/jobs/${listing.id}`} className="hover:underline">
                      {displayTitle(listing.title)}
                    </Link>
                  </div>
                  {listing.application_url && (
                    <div className="mt-1 text-xs">
                      <ExternalLink href={listing.application_url}>
                        {hostOf(listing.application_url) ?? "Open"}
                      </ExternalLink>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Raw source data" className="lg:col-span-3">
          <details>
            <summary className="cursor-pointer text-sm text-slate-600 dark:text-slate-300">
              Show what the source returned (for debugging)
            </summary>
            <pre className="mt-3 max-h-96 overflow-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-950">
              {JSON.stringify(job.raw_content, null, 2)}
            </pre>
          </details>
        </Card>
      </div>
    </>
  );
}
