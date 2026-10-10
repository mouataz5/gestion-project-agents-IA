import Link from "next/link";

import type { JobRead } from "@/lib/api/types";
import { humanize } from "@/lib/format";
import {
  displayCompany,
  displayTitle,
  postingDateLabel,
  postingDateTone,
  windowLabel,
} from "@/lib/jobs";

import { AtsScoreBadge } from "./ats-score";
import { RecommendationBadge, VisaBadge } from "./job-analysis";
import { Badge, EmptyState, StatusBadge } from "./ui";

export function PostingDateBadge({
  job,
  hours,
}: {
  job: Pick<JobRead, "posted_at" | "posting_date_status" | "posting_date_basis" | "window_status">;
  hours: number;
}) {
  const tooltip = [windowLabel(job.window_status, hours), job.posting_date_basis]
    .filter(Boolean)
    .join(" — ");
  return (
    <span title={tooltip} data-testid="posting-date">
      <Badge tone={postingDateTone(job.posting_date_status)}>{postingDateLabel(job)}</Badge>
    </span>
  );
}

export function JobsTable({
  jobs,
  hours,
  timeZone,
  empty,
  target = 95,
}: {
  jobs: JobRead[];
  hours: number;
  timeZone: string;
  empty: string;
  /** ATS_TARGET_SCORE, to colour the ATS scores. */
  target?: number;
}) {
  if (jobs.length === 0) return <EmptyState>{empty}</EmptyState>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" data-timezone={timeZone}>
        <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
          <tr className="border-b border-slate-200 dark:border-slate-800">
            <th className="py-2 pr-4 font-medium">Job</th>
            <th className="py-2 pr-4 font-medium">Location</th>
            <th className="py-2 pr-4 font-medium">Posted</th>
            <th className="py-2 pr-4 font-medium">Source</th>
            <th className="py-2 pr-4 font-medium">Analysis</th>
            <th className="py-2 pr-4 font-medium">ATS</th>
            <th className="py-2 font-medium">Pipeline</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.id}
              data-testid="job-row"
              className="border-b border-slate-100 align-top last:border-0 dark:border-slate-800/60"
            >
              <td className="py-2.5 pr-4">
                <Link
                  href={`/jobs/${job.id}`}
                  className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                >
                  {displayTitle(job.title)}
                </Link>
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <span>{displayCompany(job.company)}</span>
                  {job.duplicate_of_id && <Badge tone="neutral">Duplicate listing</Badge>}
                  {job.duplicate_count > 0 && (
                    <span title="The same job was also found on other sources">
                      +{job.duplicate_count} other listing{job.duplicate_count > 1 ? "s" : ""}
                    </span>
                  )}
                </div>
              </td>
              <td className="py-2.5 pr-4">
                <div>{job.location ?? "—"}</div>
                {job.remote_status !== "UNKNOWN" && (
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {humanize(job.remote_status)}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-4 whitespace-nowrap">
                <PostingDateBadge job={job} hours={hours} />
              </td>
              <td className="py-2.5 pr-4 font-mono text-xs">{job.source}</td>
              <td className="py-2.5 pr-4">
                {job.recommendation || job.visa_status ? (
                  <div className="flex flex-col items-start gap-1">
                    {job.recommendation && (
                      <RecommendationBadge recommendation={job.recommendation} />
                    )}
                    {job.visa_status && <VisaBadge status={job.visa_status} />}
                  </div>
                ) : (
                  <span className="text-xs text-slate-400">—</span>
                )}
              </td>
              <td className="py-2.5 pr-4 whitespace-nowrap">
                {job.ats_score !== null && job.tailored_cv_id ? (
                  <AtsScoreBadge
                    score={job.ats_score}
                    target={target}
                    href={`/cv/tailored/${job.tailored_cv_id}`}
                  />
                ) : (
                  <span className="text-xs text-slate-400">—</span>
                )}
              </td>
              <td className="py-2.5">
                {job.application_status ? (
                  <StatusBadge status={job.application_status} />
                ) : (
                  <span className="text-xs text-slate-400">Not queued</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
