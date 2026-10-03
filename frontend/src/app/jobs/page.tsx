import type { Metadata } from "next";
import Link from "next/link";

import { buttonClass, controlClass } from "@/components/form";
import { JobImportForm } from "@/components/job-import-form";
import { JobSourcesTable } from "@/components/job-sources-table";
import { JobsTable } from "@/components/jobs-table";
import { RunAnalysisButton, RunDiscoveryButton } from "@/components/start-run-button";
import { BackendError, Card, PageHeader } from "@/components/ui";
import { recommendationLabel, visaLabel } from "@/lib/analysis";
import {
  type JobPage,
  type JobSource,
  type JobStats,
  RECOMMENDATIONS,
  type SystemInfo,
  VISA_STATUSES,
} from "@/lib/api/types";
import {
  hasActiveFilters,
  JOB_PAGE_SIZE,
  type JobFilters,
  type JobTab,
  jobsApiParams,
  jobsHref,
  parseJobFilters,
  tabLabel,
} from "@/lib/jobs";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Jobs" };

const TABS: readonly JobTab[] = ["recent", "all", "unknown"];

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

function FilterBar({ filters, sources }: { filters: JobFilters; sources: JobSource[] }) {
  const active = hasActiveFilters(filters);
  return (
    <form method="get" action="/jobs" className="flex flex-wrap items-end gap-3" role="search">
      {filters.tab !== "recent" && <input type="hidden" name="tab" value={filters.tab} />}
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        Search
        <input
          type="search"
          name="q"
          defaultValue={filters.q}
          placeholder="Title, company or location"
          className={`${controlClass(false, true)} w-64`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        Source
        <select
          name="source"
          defaultValue={filters.source ?? ""}
          className={controlClass(false, true)}
        >
          <option value="">All sources</option>
          {sources.map((source) => (
            <option key={source.key} value={source.key}>
              {source.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        Country
        <input
          name="country"
          defaultValue={filters.country}
          placeholder="FR"
          maxLength={2}
          pattern="[A-Za-z]{2}"
          title="Two-letter country code"
          className={`${controlClass(false, true)} w-20 uppercase`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        Recommendation
        <select
          name="recommendation"
          defaultValue={filters.recommendation ?? ""}
          className={controlClass(false, true)}
        >
          <option value="">Any</option>
          {RECOMMENDATIONS.map((recommendation) => (
            <option key={recommendation} value={recommendation}>
              {recommendationLabel(recommendation)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        Visa
        <select name="visa" defaultValue={filters.visa ?? ""} className={controlClass(false, true)}>
          <option value="">Any</option>
          {VISA_STATUSES.map((status) => (
            <option key={status} value={status}>
              {visaLabel(status)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 pb-2 text-sm text-slate-600 dark:text-slate-300">
        <input
          type="checkbox"
          name="duplicates"
          value="1"
          defaultChecked={filters.duplicates}
          className="h-4 w-4 rounded border-slate-300 text-indigo-600"
        />
        Show duplicate listings
      </label>
      <div className="flex gap-2 pb-px">
        <button type="submit" className={buttonClass("secondary")}>
          Apply
        </button>
        {active && (
          <Link href={jobsHref({ tab: filters.tab })} className={buttonClass("ghost")}>
            Reset
          </Link>
        )}
      </div>
    </form>
  );
}

export default async function JobsPage(props: PageProps<"/jobs">) {
  const filters = parseJobFilters(await props.searchParams);
  const [jobsResult, statsResult, sourcesResult, infoResult] = await Promise.all([
    backendGet<JobPage>("/jobs", jobsApiParams(filters, JOB_PAGE_SIZE)),
    backendGet<JobStats>("/jobs/stats"),
    backendGet<JobSource[]>("/job-sources"),
    backendGet<SystemInfo>("/system/info"),
  ]);
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";
  const hours = jobsResult.ok
    ? jobsResult.data.window.lookback_hours
    : infoResult.ok
      ? infoResult.data.config.job_lookback_hours
      : 24;
  const sources = sourcesResult.ok ? sourcesResult.data : [];
  const listedSources = sources.filter((source) => source.policy !== "disabled");

  return (
    <>
      <PageHeader
        title="Jobs"
        description={`Jobs found by discovery runs and imports. A job counts as recent only when its posting date is known or safely estimated within the last ${hours} hours.`}
        action={
          <div className="flex flex-wrap items-start gap-2">
            <JobImportForm />
            <RunDiscoveryButton />
            <RunAnalysisButton variant="secondary" />
          </div>
        }
      />

      {statsResult.ok && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4" data-testid="job-stats">
          <Stat label="Found today" value={statsResult.data.found_today} />
          <Stat label={`Posted in the last ${hours} h`} value={statsResult.data.in_window} />
          <Stat
            label="Date unknown"
            value={statsResult.data.unknown_date}
            hint="Never counted as recent"
          />
          <Stat
            label="Duplicate listings merged"
            value={statsResult.data.duplicates}
            hint={`${statsResult.data.total} unique jobs`}
          />
        </div>
      )}

      <Card>
        <nav className="mb-4 flex flex-wrap gap-2" aria-label="Posting window">
          {TABS.map((tab) => {
            const selected = tab === filters.tab;
            return (
              <Link
                key={tab}
                href={jobsHref({ ...filters, tab, offset: 0 })}
                aria-current={selected ? "page" : undefined}
                className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
                  selected
                    ? "bg-indigo-600 text-white ring-indigo-600"
                    : "text-slate-600 ring-slate-300 hover:bg-slate-100 dark:text-slate-300 dark:ring-slate-700 dark:hover:bg-slate-800"
                }`}
              >
                {tabLabel(tab, hours)}
              </Link>
            );
          })}
        </nav>
        <div className="mb-4">
          <FilterBar filters={filters} sources={listedSources} />
        </div>

        {jobsResult.ok ? (
          <>
            <JobsTable
              jobs={jobsResult.data.items}
              hours={hours}
              timeZone={timeZone}
              empty={
                filters.tab === "recent" && !hasActiveFilters(filters)
                  ? `No job posted in the last ${hours} hours yet. Run a discovery or import a job URL.`
                  : "No job matches these filters."
              }
            />
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-slate-500 dark:text-slate-400" data-testid="jobs-total">
                {jobsResult.data.total === 0
                  ? "No jobs"
                  : `Showing ${filters.offset + 1}–${filters.offset + jobsResult.data.items.length} of ${jobsResult.data.total}`}
              </span>
              <div className="flex gap-2">
                {filters.offset > 0 && (
                  <Link
                    className="rounded-md px-3 py-1 ring-1 ring-slate-300 dark:ring-slate-700"
                    href={jobsHref({
                      ...filters,
                      offset: Math.max(0, filters.offset - JOB_PAGE_SIZE),
                    })}
                  >
                    Previous
                  </Link>
                )}
                {filters.offset + JOB_PAGE_SIZE < jobsResult.data.total && (
                  <Link
                    className="rounded-md px-3 py-1 ring-1 ring-slate-300 dark:ring-slate-700"
                    href={jobsHref({ ...filters, offset: filters.offset + JOB_PAGE_SIZE })}
                  >
                    Next
                  </Link>
                )}
              </div>
            </div>
          </>
        ) : (
          <BackendError message={jobsResult.message} />
        )}
      </Card>

      <Card title="Sources" className="mt-6">
        {sourcesResult.ok ? (
          <JobSourcesTable sources={sources} timeZone={timeZone} />
        ) : (
          <BackendError message={sourcesResult.message} />
        )}
      </Card>
    </>
  );
}
