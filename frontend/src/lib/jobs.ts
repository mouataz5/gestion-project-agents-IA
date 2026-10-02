/**
 * Pure helpers for the jobs pages: URL filters, API query parameters and labels for posting
 * dates, salaries and imported jobs whose fields were not provided.
 */
import type { JobRead, PostingDateStatus, WindowStatus } from "@/lib/api/types";
import { formatRelative, type Tone } from "@/lib/format";

/** Tabs of the jobs list: posted in the window (default), every job, or date unknown. */
export type JobTab = "recent" | "all" | "unknown";

export interface JobFilters {
  tab: JobTab;
  source?: string;
  country?: string;
  q?: string;
  duplicates: boolean;
  offset: number;
}

export const DEFAULT_JOB_FILTERS: JobFilters = { tab: "recent", duplicates: false, offset: 0 };
export const JOB_PAGE_SIZE = 25;

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Filters from the page URL. Anything malformed is ignored rather than sent to the API. */
export function parseJobFilters(params: SearchParams): JobFilters {
  const tab = first(params.tab);
  const source = first(params.source)?.trim();
  const country = first(params.country)?.trim();
  const q = first(params.q)?.trim().slice(0, 200);
  const duplicates = first(params.duplicates);
  const offset = Number.parseInt(first(params.offset) ?? "0", 10);
  return {
    tab: tab === "all" || tab === "unknown" ? tab : "recent",
    source: source && /^[a-z][a-z0-9_]{1,49}$/.test(source) ? source : undefined,
    country: country && /^[A-Za-z]{2}$/.test(country) ? country.toUpperCase() : undefined,
    q: q || undefined,
    duplicates: duplicates === "1" || duplicates === "true",
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

/** Query parameters of ``GET /jobs`` for the given filters. */
export function jobsApiParams(
  filters: JobFilters,
  limit: number = JOB_PAGE_SIZE,
): Record<string, string | number | undefined> {
  return {
    window: filters.tab === "recent" ? "in_window" : "all",
    date_status: filters.tab === "unknown" ? "UNKNOWN" : undefined,
    source: filters.source,
    country: filters.country,
    q: filters.q,
    include_duplicates: filters.duplicates ? "true" : undefined,
    limit,
    offset: filters.offset || undefined,
  };
}

/** Link to the jobs list; default values are left out so URLs stay short. */
export function jobsHref(filters: Partial<JobFilters>): string {
  const params = new URLSearchParams();
  if (filters.tab && filters.tab !== "recent") params.set("tab", filters.tab);
  if (filters.source) params.set("source", filters.source);
  if (filters.country) params.set("country", filters.country);
  if (filters.q) params.set("q", filters.q);
  if (filters.duplicates) params.set("duplicates", "1");
  if (filters.offset && filters.offset > 0) params.set("offset", String(filters.offset));
  const query = params.toString();
  return query ? `/jobs?${query}` : "/jobs";
}

export function tabLabel(tab: JobTab, lookbackHours: number): string {
  if (tab === "recent") return `Last ${lookbackHours} h`;
  return tab === "all" ? "All jobs" : "Date unknown";
}

/** "Posted 3 h ago", "≈ 2 d ago (estimated)" or "Date unknown". */
export function postingDateLabel(
  job: Pick<JobRead, "posted_at" | "posting_date_status">,
  now: Date = new Date(),
): string {
  if (job.posting_date_status === "UNKNOWN" || !job.posted_at) return "Date unknown";
  const relative = formatRelative(job.posted_at, now);
  return job.posting_date_status === "KNOWN" ? `Posted ${relative}` : `≈ ${relative} (estimated)`;
}

export function postingDateTone(status: PostingDateStatus): Tone {
  if (status === "KNOWN") return "success";
  return status === "ESTIMATED" ? "warning" : "neutral";
}

export function windowLabel(status: WindowStatus, lookbackHours: number): string {
  if (status === "IN_WINDOW") return `In the last ${lookbackHours} h`;
  return status === "OUT_OF_WINDOW" ? `Older than ${lookbackHours} h` : "Date unknown";
}

const NUMBER = new Intl.NumberFormat("en-US");

/** "65,000–80,000 EUR / year"; null when no salary was published. */
export function formatSalary(
  job: Pick<JobRead, "salary_min" | "salary_max" | "salary_currency" | "salary_period">,
): string | null {
  const { salary_min: min, salary_max: max } = job;
  if (min == null && max == null) return null;
  let amount: string;
  if (min != null && max != null && min !== max)
    amount = `${NUMBER.format(min)}–${NUMBER.format(max)}`;
  else if (min != null && max != null) amount = NUMBER.format(min);
  else if (min != null) amount = `from ${NUMBER.format(min)}`;
  else amount = `up to ${NUMBER.format(max as number)}`;
  const currency = job.salary_currency ? ` ${job.salary_currency}` : "";
  const period = job.salary_period ? ` / ${job.salary_period}` : "";
  return `${amount}${currency}${period}`;
}

/** Imported links may have no title or company: they are shown as such, never guessed. */
export function displayTitle(title: string): string {
  return title.trim() || "Untitled job";
}

export function displayCompany(company: string): string {
  return company.trim() || "Unknown company";
}

/** "linkedin.com" for a job URL (null when the URL is missing or invalid). */
export function hostOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return null;
  }
}

const IMPORT_ERRORS: Record<string, string> = {
  unsafe_url:
    "This URL cannot be imported: only public http(s) job pages are accepted (no local or private addresses, no credentials in the URL).",
  validation_error: "Check the fields: a job URL is required.",
  payload_too_large: "The request is too large.",
};

export function importErrorMessage(code: string | undefined, fallback: string): string {
  return (code && IMPORT_ERRORS[code]) || fallback;
}
