/**
 * Pure helpers for job analyses: labels and tones for recommendations, visa statuses and match
 * results, provenance (provider, model, tokens) and highlighting of verbatim visa quotes.
 */
import type {
  JobAnalysis,
  LanguageCheck,
  Recommendation,
  RelevanceResult,
  RunDetail,
  VisaEvidence,
  VisaResult,
  VisaStatus,
} from "@/lib/api/types";
import type { Tone } from "@/lib/format";

const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  APPLY: "Apply",
  REVIEW: "Review",
  SKIP: "Skip",
};
const RECOMMENDATION_TONES: Record<Recommendation, Tone> = {
  APPLY: "success",
  REVIEW: "warning",
  SKIP: "neutral",
};

export function recommendationLabel(recommendation: Recommendation): string {
  return RECOMMENDATION_LABELS[recommendation];
}

export function recommendationTone(recommendation: Recommendation): Tone {
  return RECOMMENDATION_TONES[recommendation];
}

const VISA_LABELS: Record<VisaStatus, string> = {
  SPONSORSHIP_CONFIRMED: "Sponsorship confirmed",
  SPONSORSHIP_LIKELY: "Sponsorship likely",
  SPONSORSHIP_UNKNOWN: "Sponsorship not mentioned",
  SPONSORSHIP_NOT_AVAILABLE: "No sponsorship",
};
const VISA_TONES: Record<VisaStatus, Tone> = {
  SPONSORSHIP_CONFIRMED: "success",
  SPONSORSHIP_LIKELY: "info",
  SPONSORSHIP_UNKNOWN: "neutral",
  SPONSORSHIP_NOT_AVAILABLE: "danger",
};

export function visaLabel(status: VisaStatus): string {
  return VISA_LABELS[status];
}

export function visaTone(status: VisaStatus): Tone {
  return VISA_TONES[status];
}

const SIGNAL_LABELS: Record<VisaEvidence["signal"], string> = {
  POSITIVE: "Offers sponsorship",
  LIKELY: "Suggests sponsorship",
  NEGATIVE: "Rules out sponsorship",
  RELOCATION: "Relocation support",
};
const EVIDENCE_SOURCES: Record<VisaEvidence["source"], string> = {
  RULE: "phrase rule",
  LLM: "model quote, found in the posting",
};

/** "Rules out sponsorship · phrase rule". */
export function evidenceLabel(evidence: Pick<VisaEvidence, "signal" | "source">): string {
  return `${SIGNAL_LABELS[evidence.signal]} · ${EVIDENCE_SOURCES[evidence.source]}`;
}

/** Whether the candidate needs a sponsor for this job (computed from the profile, never guessed). */
export function sponsorshipNeedLabel(
  visa: Pick<VisaResult, "sponsorship_needed" | "country_code">,
): string {
  const where = visa.country_code ? ` to work in ${visa.country_code}` : "";
  if (visa.sponsorship_needed === true) return `You need sponsorship${where}.`;
  if (visa.sponsorship_needed === false) return `You do not need sponsorship${where}.`;
  if (!visa.country_code) return "Unknown: the posting does not say which country the job is in.";
  return `Unknown: your profile does not say whether you need sponsorship in ${visa.country_code}.`;
}

/** "3 of 4 required skills backed by your CV (75%)". */
export function coverageLabel(
  relevance: Pick<RelevanceResult, "required_count" | "required_coverage">,
): string {
  const { required_count: count, required_coverage: coverage } = relevance;
  if (!count || coverage === null) return "The posting lists no required skills";
  const matched = Math.round(coverage * count);
  return `${matched} of ${count} required skills backed by your CV (${Math.round(coverage * 100)}%)`;
}

const RELEVANCE_LABELS: Record<RelevanceResult["role_relevance"], string> = {
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
};
const RELEVANCE_TONES: Record<RelevanceResult["role_relevance"], Tone> = {
  HIGH: "success",
  MEDIUM: "warning",
  LOW: "neutral",
};

export function relevanceLabel(level: RelevanceResult["role_relevance"]): string {
  return RELEVANCE_LABELS[level];
}

export function relevanceTone(level: RelevanceResult["role_relevance"]): Tone {
  return RELEVANCE_TONES[level];
}

const SENIORITY_LABELS: Record<RelevanceResult["seniority_fit"], string> = {
  MATCH: "Matches your experience",
  UNDER_QUALIFIED: "The role is more senior",
  OVER_QUALIFIED: "The role is more junior",
  UNKNOWN: "Not stated in the posting",
};

export function seniorityLabel(fit: RelevanceResult["seniority_fit"]): string {
  return SENIORITY_LABELS[fit];
}

/** The candidate's level for a language the posting mentions (never guessed). */
export function candidateLanguageLabel(
  check: Pick<LanguageCheck, "candidate_level" | "met">,
): string {
  if (check.candidate_level) return check.candidate_level;
  if (check.met === false) return "not in your profile or CV";
  if (check.met === null) return "not stated in your profile or CV";
  return "level not stated";
}

export function languageStatus(check: LanguageCheck): { label: string; tone: Tone } {
  if (check.met === true) return { label: "Met", tone: "success" };
  if (check.met === null) return { label: "Unknown", tone: "warning" };
  return check.required
    ? { label: "Missing", tone: "danger" }
    : { label: "Nice to have", tone: "neutral" };
}

const PROVIDER_NAMES: Record<string, string> = { claude: "Claude" };

/** "Claude · claude-opus-5-5", with the fallback model when another model answered. */
export function providerLabel(
  analysis: Pick<
    JobAnalysis,
    "is_mock" | "provider" | "requested_model" | "served_model" | "fallback_used"
  >,
): string {
  if (analysis.is_mock) return "Offline mock analysis (no language model)";
  const name = PROVIDER_NAMES[analysis.provider] ?? analysis.provider;
  const model = analysis.served_model ?? analysis.requested_model;
  const fallback =
    analysis.fallback_used && model !== analysis.requested_model
      ? ` (refusal fallback from ${analysis.requested_model})`
      : "";
  return `${name} · ${model}${fallback}`;
}

const NUMBER = new Intl.NumberFormat("en-US");

/** "1,200 input · 9,000 from cache · 300 output tokens". */
export function usageLabel(usage: JobAnalysis["usage"]): string {
  const total =
    usage.input_tokens +
    usage.output_tokens +
    usage.cache_read_input_tokens +
    usage.cache_creation_input_tokens;
  if (total === 0) return "No tokens used";
  const parts = [`${NUMBER.format(usage.input_tokens)} input`];
  if (usage.cache_read_input_tokens)
    parts.push(`${NUMBER.format(usage.cache_read_input_tokens)} from cache`);
  if (usage.cache_creation_input_tokens)
    parts.push(`${NUMBER.format(usage.cache_creation_input_tokens)} written to cache`);
  parts.push(`${NUMBER.format(usage.output_tokens)} output tokens`);
  return parts.join(" · ");
}

/** Why an analysis has no result (null when it succeeded). */
export function analysisProblem(
  analysis: Pick<JobAnalysis, "status" | "error_code" | "error_message">,
): string | null {
  if (analysis.status === "REFUSED")
    return "The model declined to analyse this posting. Review it yourself, or re-analyse it later.";
  if (analysis.status === "FAILED")
    return `The analysis failed: ${analysis.error_message ?? analysis.error_code ?? "unknown error"}`;
  return null;
}

/** What to tell the user when an analysis run they started from a job page has finished. */
export function runOutcomeMessage(
  run: Pick<RunDetail, "status"> & {
    events: ReadonlyArray<Pick<RunDetail["events"][number], "level" | "message">>;
  },
): string | null {
  if (run.status === "FAILED" || run.status === "CANCELLED")
    return `The analysis run ${run.status === "FAILED" ? "failed" : "was cancelled"}: open the run for details.`;
  const warning = run.events.find((event) => event.level === "WARNING");
  return warning ? warning.message : null;
}

export interface TextSegment {
  text: string;
  quote: boolean;
}

const EQUIVALENT_CHARACTERS: ReadonlyArray<[RegExp, string]> = [
  [/['‘’]/, "['‘’]"],
  [/["“”„]/, '["“”„]'],
  [/[-‐‑‒–—]/, "[-‐‑‒–—]"],
];

// Punctuation around a quote ("…sponsorship;" vs "…sponsorship.") is not part of the evidence.
const QUOTE_EDGES = /^[\s"'“”‘’«»()[\].,;:!?…-]+|[\s"'“”‘’«»()[\].,;:!?…-]+$/gu;

function quotePattern(quote: string): string {
  let pattern = "";
  let space = false;
  for (const character of quote.replace(QUOTE_EDGES, "")) {
    if (/\s/.test(character)) {
      space = true;
      continue;
    }
    if (space) pattern += "\\s+";
    space = false;
    const equivalent = EQUIVALENT_CHARACTERS.find(([test]) => test.test(character));
    pattern += equivalent ? equivalent[1] : character.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
  }
  return pattern;
}

/** Splits ``text`` into plain and quoted segments (quotes matched ignoring case and spacing). */
export function highlightQuotes(text: string, quotes: readonly string[]): TextSegment[] {
  if (!text) return [];
  const ranges: Array<[number, number]> = [];
  for (const quote of quotes) {
    const pattern = quotePattern(quote);
    if (!pattern) continue;
    for (const match of text.matchAll(new RegExp(pattern, "giu"))) {
      ranges.push([match.index, match.index + match[0].length]);
    }
  }
  if (ranges.length === 0) return [{ text, quote: false }];
  ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const merged: Array<[number, number]> = [];
  for (const [start, end] of ranges) {
    const last = merged.at(-1);
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  const segments: TextSegment[] = [];
  let position = 0;
  for (const [start, end] of merged) {
    if (start > position) segments.push({ text: text.slice(position, start), quote: false });
    segments.push({ text: text.slice(start, end), quote: true });
    position = end;
  }
  if (position < text.length) segments.push({ text: text.slice(position), quote: false });
  return segments;
}
