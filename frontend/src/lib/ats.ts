/**
 * Pure helpers for tailored CVs and ATS scores: score summaries against the target and the
 * supported ceiling, component rows, keyword groups, gaps, stop reasons and evidence labels.
 */
import type {
  AtsIteration,
  ComponentScore,
  Gap,
  GapKind,
  IterationStatus,
  KeywordResult,
  LedgerEntry,
  LedgerOrigin,
  StopReason,
  TailoringRead,
} from "@/lib/api/types";
import type { Tone } from "@/lib/format";

const STOP_REASONS: Record<StopReason, { label: string; explanation: string }> = {
  TARGET_REACHED: {
    label: "Target reached",
    explanation: "The tailored CV reached the target score.",
  },
  ONLY_UNSUPPORTED_GAINS: {
    label: "Only unsupported gains left",
    explanation:
      "The CV is as close to the job as your master CV allows: a higher score would need skills or experience your CV does not show.",
  },
  NO_IMPROVEMENT: {
    label: "No further improvement",
    explanation: "The last rewrite did not improve the score by half a point or more.",
  },
  MAX_ITERATIONS: {
    label: "Iteration limit reached",
    explanation: "The tailoring stopped after ATS_MAX_ITERATIONS rewrites.",
  },
  GUARD_REJECTED: {
    label: "Rewrites rejected",
    explanation:
      "Two rewrites in a row broke the truthfulness rules: the best truthful version was kept.",
  },
  PROVIDER_ERROR: {
    label: "The model did not answer",
    explanation: "The language model failed or declined to answer.",
  },
};

export function stopReasonLabel(reason: StopReason): string {
  return STOP_REASONS[reason].label;
}

export function stopReasonExplanation(reason: StopReason): string {
  return STOP_REASONS[reason].explanation;
}

function score(value: number): string {
  return value.toFixed(1);
}

/** "82.3 → 88.3", or "65.7, your master CV as it is" when no rewrite beat it. */
export function scoreSummary(
  tailoring: Pick<TailoringRead, "baseline_score" | "final_score" | "best_iteration">,
): string {
  const { baseline_score: baseline, final_score: final } = tailoring;
  if (final === null) return baseline === null ? "Not scored" : `${score(baseline)} (no CV stored)`;
  if (baseline === null) return score(final);
  if (tailoring.best_iteration === 0 || final === baseline)
    return `${score(final)}, your master CV as it is`;
  return `${score(baseline)} → ${score(final)}`;
}

/** Success at the target, info at the supported ceiling, warning below both. */
export function scoreTone(
  value: number | null,
  target: number,
  ceiling: number | null | undefined,
): Tone {
  if (value === null) return "neutral";
  if (value >= target) return "success";
  if (ceiling !== null && ceiling !== undefined && value >= ceiling - 0.5) return "info";
  return "warning";
}

/** "Scored on 65 of 100 points: the posting states no years, responsibilities or degree." */
export function assessedLabel(assessed: number | null | undefined): string | null {
  if (assessed === null || assessed === undefined || assessed >= 100) return null;
  return `Scored on ${assessed} of 100 points: the posting does not state everything the score looks at.`;
}

const COMPONENT_LABELS: Record<string, string> = {
  keywords: "Job keywords",
  skills: "Skills listed and shown",
  experience: "Years of experience",
  responsibilities: "Responsibilities covered",
  title: "Job title",
  education: "Education",
  formatting: "ATS-friendly structure",
};

export function componentLabel(name: string): string {
  return COMPONENT_LABELS[name] ?? name;
}

export interface ComponentRow {
  name: string;
  label: string;
  weight: number;
  /** 0..100, or null when the posting gives nothing to compare with. */
  percent: number | null;
  /** Points out of 100 after the weights of components that do not apply are redistributed. */
  points: number | null;
}

export function componentRows(components: readonly ComponentScore[]): ComponentRow[] {
  const assessed = components.reduce(
    (total, component) => total + (component.applicable ? component.weight : 0),
    0,
  );
  return components.map((component) => {
    const applicable = component.applicable && component.score !== null && assessed > 0;
    return {
      name: component.name,
      label: componentLabel(component.name),
      weight: component.weight,
      percent: applicable ? Math.round((component.score ?? 0) * 100) : null,
      points: applicable
        ? Math.round(((component.weight * (component.score ?? 0) * 100) / assessed) * 10) / 10
        : null,
    };
  });
}

export interface KeywordGroups {
  matched: KeywordResult[];
  available: KeywordResult[];
  missing: KeywordResult[];
  unsupported: KeywordResult[];
}

export function keywordGroups(keywords: readonly KeywordResult[]): KeywordGroups {
  const groups: KeywordGroups = { matched: [], available: [], missing: [], unsupported: [] };
  for (const keyword of keywords) {
    if (keyword.status === "MATCHED") groups.matched.push(keyword);
    else if (keyword.status === "AVAILABLE") groups.available.push(keyword);
    else if (keyword.status === "MISSING") groups.missing.push(keyword);
    else groups.unsupported.push(keyword);
  }
  return groups;
}

/** Where a matched keyword appears: "summary or skills", "experience", "languages". */
export function keywordPlacement(
  keyword: Pick<KeywordResult, "prominent" | "listed" | "demonstrated" | "category">,
): string {
  const places: string[] = [];
  if (keyword.listed) places.push("skills");
  if (keyword.demonstrated) places.push("experience");
  if (places.length === 0 && keyword.prominent)
    places.push(keyword.category === "spoken_language" ? "languages" : "summary");
  return places.length ? `in your ${places.join(" and ")}` : "in your CV";
}

/** The version that was stored, else the master CV's score (iteration 0). */
export function selectedIteration(iterations: readonly AtsIteration[]): AtsIteration | undefined {
  return iterations.find((iteration) => iteration.selected) ?? iterations[0];
}

const GAP_LABELS: Record<GapKind, string> = {
  MISSING_KEYWORD: "Not in your master CV",
  NOT_DEMONSTRATED: "Listed, never shown in a role",
  RESPONSIBILITY: "Responsibility not covered",
  TITLE_TERMS: "Job-title words",
};

export function gapLabel(kind: GapKind): string {
  return GAP_LABELS[kind];
}

export function gapTone(gap: Pick<Gap, "kind" | "importance">): Tone {
  if (gap.kind === "MISSING_KEYWORD") return gap.importance === "REQUIRED" ? "danger" : "warning";
  return "neutral";
}

const ORIGINS: Record<LedgerOrigin, { label: string; tone: Tone; help: string }> = {
  VERBATIM: { label: "Verbatim", tone: "success", help: "Copied unchanged from your master CV" },
  REWRITTEN: {
    label: "Reworded",
    tone: "info",
    help: "Reworded from the cited lines of your master CV, checked by the truthfulness guard",
  },
  REVERTED: {
    label: "Reverted",
    tone: "warning",
    help: "A rewrite broke the truthfulness rules: your master CV's line is used instead",
  },
  COPIED: { label: "Copied", tone: "neutral", help: "A fact copied from your master CV" },
  SELECTED: { label: "Selected", tone: "neutral", help: "A skill your master CV backs" },
  RETITLED: { label: "Retitled", tone: "info", help: "A title you allow the tailoring to adjust" },
};

export function originLabel(origin: LedgerOrigin): string {
  return ORIGINS[origin].label;
}

export function originTone(origin: LedgerOrigin): Tone {
  return ORIGINS[origin].tone;
}

export function originHelp(origin: LedgerOrigin): string {
  return ORIGINS[origin].help;
}

export function ledgerByPath(ledger: readonly LedgerEntry[]): Map<string, LedgerEntry> {
  return new Map(ledger.map((entry) => [entry.path, entry]));
}

const ITERATION_LABELS: Record<IterationStatus, string> = {
  SCORED: "Scored",
  REPAIRED: "Scored after repairs",
  REJECTED: "Rejected by the guard",
  FAILED: "Call failed",
  REFUSED: "Model declined",
};

export function iterationStatusLabel(status: IterationStatus): string {
  return ITERATION_LABELS[status];
}

export function iterationTone(status: IterationStatus): Tone {
  if (status === "SCORED") return "success";
  if (status === "REPAIRED") return "info";
  if (status === "REJECTED") return "warning";
  return "danger";
}

/** Why a tailoring stored no CV (null when it did). */
export function tailoringProblem(
  tailoring: Pick<TailoringRead, "status" | "error_message" | "error_code">,
): string | null {
  if (tailoring.status === "REFUSED")
    return "The model declined to tailor this CV. The job stays qualified: try again later.";
  if (tailoring.status === "FAILED")
    return `The tailoring failed: ${tailoring.error_message ?? tailoring.error_code ?? "unknown error"}. The job stays qualified.`;
  return null;
}

export const STALE_NOTICE =
  "Built from an earlier master CV: re-tailor it so it reflects your current master CV.";
