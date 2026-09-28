import type { Metadata } from "next";
import Link from "next/link";

import { CvDraftEditor } from "@/components/cv-editor";
import { CvReviseButton } from "@/components/cv-revise-button";
import { CvUpload } from "@/components/cv-upload";
import { CvStructureView } from "@/components/cv-view";
import { buttonClass } from "@/components/form";
import { BackendError, Card, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import type { CvVersionDetail, CvVersionSummary, SystemInfo } from "@/lib/api/types";
import { DEFAULT_MAX_UPLOAD_MB, formatBytes } from "@/lib/cv";
import { formatDateTime } from "@/lib/format";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Master CV" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Default selection: the draft awaiting review, else the active master CV, else the newest. */
function defaultVersion(versions: readonly CvVersionSummary[]): CvVersionSummary | undefined {
  return (
    versions.find((version) => version.status === "PARSED") ??
    versions.find((version) => version.status === "CONFIRMED") ??
    versions[0]
  );
}

export default async function CvPage(props: PageProps<"/cv">) {
  const searchParams = await props.searchParams;
  const requested = first(searchParams.version);

  const [versionsResult, infoResult] = await Promise.all([
    backendGet<CvVersionSummary[]>("/candidate/master-cv"),
    backendGet<SystemInfo>("/system/info"),
  ]);
  if (!versionsResult.ok) {
    return (
      <>
        <PageHeader title="Master CV" />
        <BackendError message={versionsResult.message} />
      </>
    );
  }
  const versions = versionsResult.data;
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";
  const maxBytes =
    (infoResult.ok ? infoResult.data.config.max_upload_mb : DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024;

  const selectedId = requested && UUID.test(requested) ? requested : defaultVersion(versions)?.id;
  const detailResult = selectedId
    ? await backendGet<CvVersionDetail>(`/candidate/master-cv/${selectedId}`)
    : null;
  const selected = detailResult?.ok ? detailResult.data : null;

  return (
    <>
      <PageHeader
        title="Master CV"
        description="The confirmed master CV is the only source of facts (experience, skills, dates, employers) for every later step."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Upload a new version">
          <CvUpload maxBytes={maxBytes} />
        </Card>
        <Card title={`Versions (${versions.length})`}>
          {versions.length === 0 ? (
            <EmptyState>No master CV uploaded yet.</EmptyState>
          ) : (
            <ul
              className="divide-y divide-slate-100 text-sm dark:divide-slate-800"
              data-testid="cv-versions"
            >
              {versions.map((version) => (
                <li key={version.id} className="flex items-center justify-between gap-3 py-2">
                  <Link
                    href={`/cv?version=${version.id}`}
                    className={`min-w-0 flex-1 ${version.id === selected?.id ? "font-semibold" : ""}`}
                    aria-current={version.id === selected?.id ? "true" : undefined}
                  >
                    <span className="block truncate">
                      v{version.version} · {version.original_filename}
                    </span>
                    <span className="block text-xs text-slate-500">
                      {formatDateTime(version.created_at, timeZone)} ·{" "}
                      {formatBytes(version.size_bytes)}
                      {version.warning_count > 0 ? ` · ${version.warning_count} warning(s)` : ""}
                    </span>
                  </Link>
                  <StatusBadge status={version.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {detailResult && !detailResult.ok && (
        <div className="mt-6">
          <BackendError message={detailResult.message} />
        </div>
      )}

      {selected && (
        <section className="mt-8" aria-label={`Version ${selected.version}`}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-lg font-semibold">
                Version {selected.version}
                <StatusBadge status={selected.status} />
              </h2>
              <p className="text-sm text-slate-500">
                {selected.original_filename} · parser {selected.parser_version} · language{" "}
                {selected.structure.language}
                {selected.confirmed_at &&
                  ` · confirmed ${formatDateTime(selected.confirmed_at, timeZone)}`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <a
                className={buttonClass("secondary")}
                href={`/api/backend/candidate/master-cv/${selected.id}/file`}
                download
              >
                Download original
              </a>
              {selected.status !== "PARSED" && <CvReviseButton versionId={selected.id} />}
            </div>
          </div>

          {selected.status === "PARSED" ? (
            <CvDraftEditor key={selected.id} version={selected} />
          ) : (
            <CvStructureView structure={selected.structure} />
          )}

          <details className="mt-6 rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
            <summary className="cursor-pointer font-medium">Extracted text</summary>
            <pre className="mt-3 max-h-96 overflow-auto font-mono text-xs whitespace-pre-wrap">
              {selected.extracted_text}
            </pre>
          </details>
        </section>
      )}
    </>
  );
}
