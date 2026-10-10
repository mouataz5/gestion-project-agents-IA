import Link from "next/link";
import type { ReactNode } from "react";

import { Notice } from "@/components/form";
import { providerLabel, usageLabel } from "@/lib/analysis";
import type { AtsIteration, KeywordResult, TailoringRead } from "@/lib/api/types";
import {
  STALE_NOTICE,
  assessedLabel,
  componentRows,
  gapLabel,
  gapTone,
  iterationStatusLabel,
  iterationTone,
  keywordGroups,
  keywordPlacement,
  scoreSummary,
  scoreTone,
  selectedIteration,
  stopReasonExplanation,
  stopReasonLabel,
  tailoringProblem,
} from "@/lib/ats";
import { formatDateTime, formatDuration } from "@/lib/format";

import { Badge } from "./ui";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-slate-500 dark:text-slate-400">{children}</p>;
}

function ComponentTable({ iteration }: { iteration: AtsIteration }) {
  const rows = componentRows(iteration.components);
  return (
    <table className="w-full text-left text-sm" data-testid="ats-components">
      <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
        <tr className="border-b border-slate-200 dark:border-slate-800">
          <th className="py-1.5 pr-3 font-medium">Component</th>
          <th className="py-1.5 pr-3 text-right font-medium">Weight</th>
          <th className="py-1.5 pr-3 text-right font-medium">Match</th>
          <th className="py-1.5 text-right font-medium">Points</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.name}
            className="border-b border-slate-100 last:border-0 dark:border-slate-800/60"
          >
            <td className="py-1.5 pr-3">{row.label}</td>
            <td className="py-1.5 pr-3 text-right tabular-nums">{row.weight}</td>
            <td className="py-1.5 pr-3 text-right tabular-nums">
              {row.percent === null ? (
                <span
                  className="text-xs text-slate-400"
                  title="The posting states nothing to compare with"
                >
                  n/a
                </span>
              ) : (
                `${row.percent}%`
              )}
            </td>
            <td className="py-1.5 text-right tabular-nums">{row.points ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KeywordList({
  keywords,
  tone,
  describe,
}: {
  keywords: KeywordResult[];
  tone: "success" | "info" | "neutral" | "danger";
  describe?: (keyword: KeywordResult) => string;
}) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {keywords.map((keyword) => (
        <li key={keyword.key} title={describe?.(keyword)}>
          <Badge tone={tone}>
            {keyword.term}
            {keyword.importance === "PREFERRED" && (
              <span className="font-normal opacity-75">preferred</span>
            )}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function KeywordSection({ keywords }: { keywords: KeywordResult[] }) {
  const groups = keywordGroups(keywords);
  if (keywords.length === 0)
    return <Muted>The posting names no skills, tools or languages to look for.</Muted>;
  return (
    <div className="space-y-3" data-testid="ats-keywords">
      {groups.matched.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-slate-500 dark:text-slate-400">In this CV</div>
          <KeywordList
            keywords={groups.matched}
            tone="success"
            describe={(keyword) => `${keywordPlacement(keyword)}, backed by your master CV`}
          />
        </div>
      )}
      {groups.available.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            In your master CV, not used in this version
          </div>
          <KeywordList keywords={groups.available} tone="info" />
        </div>
      )}
      {groups.missing.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            Missing — genuine gaps, never added
          </div>
          <KeywordList keywords={groups.missing} tone="neutral" />
        </div>
      )}
      <p className="text-xs text-slate-500 dark:text-slate-400" data-testid="unsupported-keywords">
        {groups.unsupported.length === 0 ? (
          "0 unsupported keywords: every keyword in this CV is backed by your master CV."
        ) : (
          <span className="font-medium text-rose-600 dark:text-rose-400">
            {groups.unsupported.length} keyword(s) without evidence:{" "}
            {groups.unsupported.map((keyword) => keyword.term).join(", ")}
          </span>
        )}
      </p>
    </div>
  );
}

function IterationTable({ iterations }: { iterations: AtsIteration[] }) {
  return (
    <table className="w-full text-left text-sm" data-testid="ats-iterations">
      <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
        <tr className="border-b border-slate-200 dark:border-slate-800">
          <th className="py-1.5 pr-3 font-medium">#</th>
          <th className="py-1.5 pr-3 font-medium">Version</th>
          <th className="py-1.5 pr-3 font-medium">Result</th>
          <th className="py-1.5 text-right font-medium">Score</th>
        </tr>
      </thead>
      <tbody>
        {iterations.map((iteration) => (
          <tr
            key={iteration.iteration}
            className="border-b border-slate-100 last:border-0 dark:border-slate-800/60"
          >
            <td className="py-1.5 pr-3 tabular-nums">{iteration.iteration}</td>
            <td className="py-1.5 pr-3">
              {iteration.document_kind === "MASTER" ? "Your master CV" : "Tailored rewrite"}
              {iteration.selected && (
                <span className="ml-2">
                  <Badge tone="success">Stored</Badge>
                </span>
              )}
            </td>
            <td className="py-1.5 pr-3">
              <Badge tone={iterationTone(iteration.status)}>
                {iterationStatusLabel(iteration.status)}
              </Badge>
              {iteration.repairs_count > 0 && (
                <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
                  {iteration.repairs_count} text(s) reverted
                </span>
              )}
              {iteration.violations.length > 0 && (
                <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
                  {iteration.violations.map((violation) => violation.detail).join("; ")}
                </span>
              )}
            </td>
            <td className="py-1.5 text-right tabular-nums">
              {iteration.score === null ? "—" : iteration.score.toFixed(1)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The latest tailoring of a job: score against the target and the ceiling, why it stopped,
 * the breakdown, the keywords and the gaps only the candidate can close. */
export function TailoringPanel({
  tailoring,
  tailoredCvId,
  timeZone,
}: {
  tailoring: TailoringRead;
  tailoredCvId: string | null;
  timeZone: string;
}) {
  const problem = tailoringProblem(tailoring);
  const best = selectedIteration(tailoring.iterations);
  const final = tailoring.final_score ?? tailoring.baseline_score;
  const assessed = assessedLabel(tailoring.assessed_weight);
  return (
    <div className="space-y-6" data-testid="tailoring">
      <div className="flex flex-wrap items-center gap-3">
        <span data-testid="ats-score-summary">
          <Badge tone={scoreTone(final, tailoring.target_score, tailoring.ceiling_score)} size="lg">
            ATS {scoreSummary(tailoring)}
          </Badge>
        </span>
        <span className="text-sm text-slate-600 dark:text-slate-300">
          target {tailoring.target_score} · reachable with your master CV{" "}
          {tailoring.ceiling_score?.toFixed(1) ?? "—"}
        </span>
        {tailoring.stop_reason && (
          <span title={stopReasonExplanation(tailoring.stop_reason)} data-testid="stop-reason">
            <Badge tone="neutral">{stopReasonLabel(tailoring.stop_reason)}</Badge>
          </span>
        )}
        {tailoring.is_mock && (
          <span title="Deterministic offline tailoring: no language model wrote this CV.">
            <Badge tone="warning">Mock tailoring</Badge>
          </span>
        )}
        {tailoredCvId && (
          <Link
            href={`/cv/tailored/${tailoredCvId}`}
            className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Open the tailored CV →
          </Link>
        )}
      </div>

      <Muted>
        {tailoring.target_score} is a target, not a promise: the tailoring only reorders, selects
        and rewords what your master CV says. Keywords it does not support are reported below, never
        added.
        {tailoring.stop_reason && ` ${stopReasonExplanation(tailoring.stop_reason)}`}
      </Muted>
      {assessed && <Muted>{assessed}</Muted>}
      {tailoring.stale && <Notice tone="warning">{STALE_NOTICE}</Notice>}
      {problem && (
        <Notice tone={tailoring.status === "FAILED" ? "error" : "warning"}>{problem}</Notice>
      )}

      {best && best.components.length > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Section title="Score breakdown">
            <ComponentTable iteration={best} />
          </Section>
          <Section title="Job keywords">
            <KeywordSection keywords={best.keywords} />
          </Section>
        </div>
      )}

      {tailoring.gaps.length > 0 && (
        <Section title="Gaps only you can close">
          <Muted>
            Add these to your master CV only if they are true; a tailored CV never adds them.
          </Muted>
          <ul className="space-y-2 text-sm" data-testid="ats-gaps">
            {tailoring.gaps.map((gap) => (
              <li key={`${gap.kind}-${gap.subject}`} className="flex flex-wrap items-start gap-2">
                <Badge tone={gapTone(gap)}>{gapLabel(gap.kind)}</Badge>
                <span>{gap.message}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Iterations">
        <IterationTable iterations={tailoring.iterations} />
      </Section>

      <p
        className="border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400"
        data-testid="tailoring-provenance"
      >
        Tailored {formatDateTime(tailoring.created_at, timeZone)} ·{" "}
        {providerLabel(tailoring, "tailoring")} · prompt {tailoring.prompt.name} v
        {tailoring.prompt.version} · scoring {tailoring.scoring_version} ·{" "}
        {tailoring.iterations_used} call(s) · {usageLabel(tailoring.usage)}
        {tailoring.duration_ms !== null && ` · ${formatDuration(tailoring.duration_ms / 1000)}`}
        {tailoring.run_id && (
          <>
            {" · "}
            <Link href={`/runs/${tailoring.run_id}`} className="underline">
              run
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
