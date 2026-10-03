import Link from "next/link";
import type { ReactNode } from "react";

import { Notice } from "@/components/form";
import {
  analysisProblem,
  candidateLanguageLabel,
  coverageLabel,
  evidenceLabel,
  highlightQuotes,
  languageStatus,
  providerLabel,
  recommendationLabel,
  recommendationTone,
  relevanceLabel,
  relevanceTone,
  seniorityLabel,
  sponsorshipNeedLabel,
  usageLabel,
  visaLabel,
  visaTone,
} from "@/lib/analysis";
import type {
  JobAnalysis,
  Recommendation,
  RelevanceResult,
  SkillMatch,
  VisaEvidence,
  VisaResult,
  VisaStatus,
} from "@/lib/api/types";
import { formatDateTime, formatDuration } from "@/lib/format";

import { Badge } from "./ui";

export function RecommendationBadge({
  recommendation,
  size,
}: {
  recommendation: Recommendation;
  size?: "sm" | "lg";
}) {
  return (
    <span data-testid="recommendation">
      <Badge tone={recommendationTone(recommendation)} size={size}>
        {recommendationLabel(recommendation)}
      </Badge>
    </span>
  );
}

export function VisaBadge({ status }: { status: VisaStatus }) {
  return (
    <span data-testid="visa-status">
      <Badge tone={visaTone(status)}>{visaLabel(status)}</Badge>
    </span>
  );
}

/** The posting text with the visa quotes the analysis relied on highlighted. */
export function HighlightedText({ text, quotes }: { text: string; quotes: readonly string[] }) {
  return (
    <>
      {highlightQuotes(text, quotes).map((segment, index) =>
        segment.quote ? (
          <mark
            key={index}
            className="rounded bg-amber-100 px-0.5 text-inherit dark:bg-amber-500/25"
          >
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}

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

function SkillChips({ matches }: { matches: SkillMatch[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {matches.map((match) => (
        <li
          key={match.job_skill}
          title={`${match.strength === "DEMONSTRATED" ? "Demonstrated in your experience" : "Listed in your skills"}${match.source === "LLM" ? `, matched by the model to ${match.candidate_skill}` : ""}`}
        >
          <Badge tone={match.strength === "DEMONSTRATED" ? "success" : "info"}>
            {match.job_skill}
            {match.source === "LLM" && match.candidate_skill !== match.job_skill && (
              <span className="font-normal opacity-75">via {match.candidate_skill}</span>
            )}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function MatchSection({ relevance }: { relevance: RelevanceResult }) {
  return (
    <div className="space-y-5" data-testid="analysis-match">
      <Section title="Role">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500 dark:text-slate-400">Relevance</span>
          <Badge tone={relevanceTone(relevance.role_relevance)}>
            {relevanceLabel(relevance.role_relevance)}
          </Badge>
        </div>
        <Muted>{relevance.role_relevance_reason}</Muted>
        <div className="text-sm">
          <span className="text-slate-500 dark:text-slate-400">Seniority: </span>
          <span className="font-medium">{seniorityLabel(relevance.seniority_fit)}</span>
        </div>
        {relevance.seniority_reason && <Muted>{relevance.seniority_reason}</Muted>}
      </Section>

      <Section title="Skills">
        <p className="text-sm font-medium" data-testid="skill-coverage">
          {coverageLabel(relevance)}
        </p>
        {relevance.required_skill_matches.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs text-slate-500 dark:text-slate-400">Required, backed</div>
            <SkillChips matches={relevance.required_skill_matches} />
          </div>
        )}
        {relevance.preferred_skill_matches.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs text-slate-500 dark:text-slate-400">Preferred, backed</div>
            <SkillChips matches={relevance.preferred_skill_matches} />
          </div>
        )}
        {relevance.skill_gaps.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs text-slate-500 dark:text-slate-400">Not backed by your CV</div>
            <ul className="flex flex-wrap gap-1.5" data-testid="skill-gaps">
              {relevance.skill_gaps.map((gap) => (
                <li key={gap}>
                  <Badge tone="neutral">{gap}</Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
        {relevance.unsupported_claims.length > 0 && (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Removed {relevance.unsupported_claims.length} match
            {relevance.unsupported_claims.length > 1 ? "es" : ""} the model claimed without evidence
            in your CV: {relevance.unsupported_claims.join("; ")}.
          </p>
        )}
      </Section>

      {relevance.language_requirements.length > 0 && (
        <Section title="Languages">
          <ul className="space-y-1 text-sm">
            {relevance.language_requirements.map((check) => {
              const status = languageStatus(check);
              return (
                <li key={check.language} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {check.language}
                    {check.level ? ` (${check.level})` : ""}
                  </span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {check.required ? "required" : "nice to have"} · you:{" "}
                    {candidateLanguageLabel(check)}
                  </span>
                  <Badge tone={status.tone}>{status.label}</Badge>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {relevance.concerns.length > 0 && (
        <Section title="Concerns">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {relevance.concerns.map((concern) => (
              <li key={concern}>{concern}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

const SIGNAL_BORDERS: Record<VisaEvidence["signal"], string> = {
  POSITIVE: "border-emerald-500",
  LIKELY: "border-sky-500",
  NEGATIVE: "border-rose-500",
  RELOCATION: "border-slate-400",
};

function VisaSection({ visa }: { visa: VisaResult }) {
  return (
    <div className="space-y-4" data-testid="analysis-visa">
      <div className="flex flex-wrap items-center gap-2">
        <VisaBadge status={visa.status} />
        {visa.relocation_available && <Badge tone="info">Relocation support</Badge>}
      </div>
      <p className="text-sm font-medium">{sponsorshipNeedLabel(visa)}</p>
      {visa.evidence.length > 0 ? (
        <ul className="space-y-3">
          {visa.evidence.map((evidence) => (
            <li key={`${evidence.signal}-${evidence.quote}`}>
              <blockquote
                className={`border-l-4 pl-3 text-sm italic ${SIGNAL_BORDERS[evidence.signal]}`}
                data-testid="visa-quote"
              >
                “{evidence.quote}”
              </blockquote>
              <div className="mt-1 pl-4 text-xs text-slate-500 dark:text-slate-400">
                {evidenceLabel(evidence)}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <Muted>The posting says nothing about visas or work authorization.</Muted>
      )}
      {visa.status !== "SPONSORSHIP_CONFIRMED" &&
        visa.status !== "SPONSORSHIP_NOT_AVAILABLE" &&
        visa.relocation_available && (
          <Muted>Relocation support alone does not mean the employer sponsors visas.</Muted>
        )}
      {visa.conflicting && (
        <Notice tone="warning">
          The posting contains contradictory statements about sponsorship: the restrictive one is
          used.
        </Notice>
      )}
      {visa.discarded_quotes.length > 0 && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Ignored {visa.discarded_quotes.length} quote
          {visa.discarded_quotes.length > 1 ? "s" : ""} the model gave that are not in the posting.
        </p>
      )}
    </div>
  );
}

/** The latest analysis of a job: decision and reasons, match, visa evidence and provenance. */
export function JobAnalysisPanel({
  analysis,
  timeZone,
}: {
  analysis: JobAnalysis;
  timeZone: string;
}) {
  const problem = analysisProblem(analysis);
  return (
    <div className="space-y-6" data-testid="job-analysis">
      <div className="flex flex-wrap items-center gap-3">
        {analysis.recommendation && (
          <RecommendationBadge recommendation={analysis.recommendation} size="lg" />
        )}
        {analysis.llm_recommendation &&
          analysis.recommendation &&
          analysis.llm_recommendation !== analysis.recommendation && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {analysis.is_mock ? "The mock analysis" : "The model"} suggested “
              {recommendationLabel(analysis.llm_recommendation)}”; the qualification rules decide.
            </span>
          )}
        {analysis.is_mock && (
          <span title="Deterministic offline analysis: no language model was used.">
            <Badge tone="warning">Mock analysis</Badge>
          </span>
        )}
      </div>

      {problem && (
        <Notice tone={analysis.status === "FAILED" ? "error" : "warning"}>{problem}</Notice>
      )}

      {analysis.rule_reasons.length > 0 && (
        <Section title="Why">
          <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="analysis-reasons">
            {analysis.rule_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          {analysis.relevance?.reasoning && (
            <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
              {analysis.relevance.reasoning}
            </p>
          )}
        </Section>
      )}

      {(analysis.relevance || analysis.visa) && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {analysis.relevance && <MatchSection relevance={analysis.relevance} />}
          {analysis.visa && (
            <Section title="Visa sponsorship">
              <VisaSection visa={analysis.visa} />
            </Section>
          )}
        </div>
      )}

      <p
        className="border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400"
        data-testid="analysis-provenance"
      >
        Analysed {formatDateTime(analysis.created_at, timeZone)} · {providerLabel(analysis)} ·
        prompt {analysis.prompt.name} v{analysis.prompt.version} · {usageLabel(analysis.usage)}
        {analysis.duration_ms !== null && ` · ${formatDuration(analysis.duration_ms / 1000)}`}
        {analysis.run_id && (
          <>
            {" · "}
            <Link href={`/runs/${analysis.run_id}`} className="underline">
              run
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
