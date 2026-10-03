import { describe, expect, it } from "vitest";

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
  runOutcomeMessage,
  seniorityLabel,
  sponsorshipNeedLabel,
  usageLabel,
  visaLabel,
  visaTone,
} from "./analysis";

describe("recommendation and visa labels", () => {
  it("labels and colours every recommendation", () => {
    expect(recommendationLabel("APPLY")).toBe("Apply");
    expect(recommendationLabel("REVIEW")).toBe("Review");
    expect(recommendationLabel("SKIP")).toBe("Skip");
    expect(recommendationTone("APPLY")).toBe("success");
    expect(recommendationTone("REVIEW")).toBe("warning");
    expect(recommendationTone("SKIP")).toBe("neutral");
  });

  it("labels and colours every visa status", () => {
    expect(visaLabel("SPONSORSHIP_CONFIRMED")).toBe("Sponsorship confirmed");
    expect(visaLabel("SPONSORSHIP_LIKELY")).toBe("Sponsorship likely");
    expect(visaLabel("SPONSORSHIP_UNKNOWN")).toBe("Sponsorship not mentioned");
    expect(visaLabel("SPONSORSHIP_NOT_AVAILABLE")).toBe("No sponsorship");
    expect(visaTone("SPONSORSHIP_CONFIRMED")).toBe("success");
    expect(visaTone("SPONSORSHIP_LIKELY")).toBe("info");
    expect(visaTone("SPONSORSHIP_UNKNOWN")).toBe("neutral");
    expect(visaTone("SPONSORSHIP_NOT_AVAILABLE")).toBe("danger");
  });

  it("says where each piece of visa evidence comes from", () => {
    expect(evidenceLabel({ signal: "NEGATIVE", source: "RULE" })).toBe(
      "Rules out sponsorship · phrase rule",
    );
    expect(evidenceLabel({ signal: "POSITIVE", source: "LLM" })).toBe(
      "Offers sponsorship · model quote, found in the posting",
    );
    expect(evidenceLabel({ signal: "RELOCATION", source: "RULE" })).toBe(
      "Relocation support · phrase rule",
    );
  });

  it("explains whether the candidate needs sponsorship", () => {
    expect(sponsorshipNeedLabel({ sponsorship_needed: true, country_code: "FR" })).toBe(
      "You need sponsorship to work in FR.",
    );
    expect(sponsorshipNeedLabel({ sponsorship_needed: false, country_code: "TN" })).toBe(
      "You do not need sponsorship to work in TN.",
    );
    expect(sponsorshipNeedLabel({ sponsorship_needed: false, country_code: null })).toBe(
      "You do not need sponsorship.",
    );
    expect(sponsorshipNeedLabel({ sponsorship_needed: null, country_code: null })).toMatch(
      /country/,
    );
    expect(sponsorshipNeedLabel({ sponsorship_needed: null, country_code: "DE" })).toMatch(
      /profile/,
    );
  });
});

describe("match labels", () => {
  it("summarises the required skills backed by the CV", () => {
    expect(coverageLabel({ required_count: 4, required_coverage: 0.75 })).toBe(
      "3 of 4 required skills backed by your CV (75%)",
    );
    expect(coverageLabel({ required_count: 3, required_coverage: 1 })).toBe(
      "3 of 3 required skills backed by your CV (100%)",
    );
    expect(coverageLabel({ required_count: 0, required_coverage: null })).toBe(
      "The posting lists no required skills",
    );
  });

  it("labels relevance and seniority", () => {
    expect(relevanceLabel("HIGH")).toBe("High");
    expect(relevanceLabel("LOW")).toBe("Low");
    expect(seniorityLabel("MATCH")).toBe("Matches your experience");
    expect(seniorityLabel("UNDER_QUALIFIED")).toBe("The role is more senior");
    expect(seniorityLabel("OVER_QUALIFIED")).toBe("The role is more junior");
    expect(seniorityLabel("UNKNOWN")).toBe("Not stated in the posting");
  });

  it("says what the candidate has for each language", () => {
    expect(candidateLanguageLabel({ candidate_level: "fluent", met: true })).toBe("fluent");
    expect(candidateLanguageLabel({ candidate_level: null, met: false })).toBe(
      "not in your profile or CV",
    );
    expect(candidateLanguageLabel({ candidate_level: null, met: null })).toBe(
      "not stated in your profile or CV",
    );
    expect(candidateLanguageLabel({ candidate_level: null, met: true })).toBe("level not stated");
  });

  it("shows language checks without guessing", () => {
    const base = { language: "German", level: "C1", candidate_level: "intermediate" };
    expect(languageStatus({ ...base, required: true, met: false })).toEqual({
      label: "Missing",
      tone: "danger",
    });
    expect(languageStatus({ ...base, required: false, met: false })).toEqual({
      label: "Nice to have",
      tone: "neutral",
    });
    expect(languageStatus({ ...base, required: true, met: true })).toEqual({
      label: "Met",
      tone: "success",
    });
    expect(languageStatus({ ...base, required: true, met: null })).toEqual({
      label: "Unknown",
      tone: "warning",
    });
  });
});

describe("provenance", () => {
  const claude = {
    is_mock: false,
    provider: "claude",
    requested_model: "claude-opus-5-5",
    served_model: "claude-opus-5-5",
    fallback_used: false,
  };

  it("names the provider and the model that answered", () => {
    expect(providerLabel(claude)).toBe("Claude · claude-opus-5-5");
    expect(providerLabel({ ...claude, served_model: "claude-opus-5", fallback_used: true })).toBe(
      "Claude · claude-opus-5 (refusal fallback from claude-opus-5-5)",
    );
    expect(
      providerLabel({
        ...claude,
        is_mock: true,
        provider: "mock",
        requested_model: "mock-deterministic-1",
        served_model: "mock-deterministic-1",
      }),
    ).toBe("Offline mock analysis (no language model)");
  });

  it("formats token usage, including the prompt cache", () => {
    expect(
      usageLabel({
        input_tokens: 1200,
        output_tokens: 300,
        cache_read_input_tokens: 9000,
        cache_creation_input_tokens: 0,
      }),
    ).toBe("1,200 input · 9,000 from cache · 300 output tokens");
    expect(
      usageLabel({
        input_tokens: 1200,
        output_tokens: 300,
        cache_read_input_tokens: 0,
        cache_creation_input_tokens: 4000,
      }),
    ).toBe("1,200 input · 4,000 written to cache · 300 output tokens");
    expect(
      usageLabel({
        input_tokens: 0,
        output_tokens: 0,
        cache_read_input_tokens: 0,
        cache_creation_input_tokens: 0,
      }),
    ).toBe("No tokens used");
  });

  it("explains refused and failed analyses", () => {
    expect(
      analysisProblem({ status: "REFUSED", error_code: "cyber", error_message: "declined" }),
    ).toMatch(/declined to analyse/);
    expect(
      analysisProblem({
        status: "FAILED",
        error_code: "llm_timeout",
        error_message: "The Anthropic API did not answer in time",
      }),
    ).toBe("The analysis failed: The Anthropic API did not answer in time");
    expect(
      analysisProblem({ status: "SUCCEEDED", error_code: null, error_message: null }),
    ).toBeNull();
  });
});

describe("analysis run outcome", () => {
  it("reports why a run analysed nothing", () => {
    const warning = {
      level: "WARNING" as const,
      message: "No confirmed master CV: upload and confirm it on the CV page.",
    };
    expect(runOutcomeMessage({ status: "SUCCEEDED", events: [warning] })).toBe(warning.message);
    expect(
      runOutcomeMessage({ status: "SUCCEEDED", events: [{ level: "INFO", message: "ok" }] }),
    ).toBeNull();
    expect(runOutcomeMessage({ status: "FAILED", events: [] })).toBe(
      "The analysis run failed: open the run for details.",
    );
  });
});

describe("quote highlighting", () => {
  const text = "We are a Paris team.\nWe  sponsor work visas for the right candidate. Apply now!";

  it("marks quotes case-insensitively across whitespace differences", () => {
    expect(highlightQuotes(text, ["we sponsor work visas for the right candidate."])).toEqual([
      { text: "We are a Paris team.\n", quote: false },
      { text: "We  sponsor work visas for the right candidate", quote: true },
      { text: ". Apply now!", quote: false },
    ]);
  });

  it("ignores punctuation at the edges of a quote", () => {
    expect(
      highlightQuotes("We are unable to offer visa sponsorship.", [
        "We are unable to offer visa sponsorship;",
      ]),
    ).toEqual([
      { text: "We are unable to offer visa sponsorship", quote: true },
      { text: ".", quote: false },
    ]);
    expect(highlightQuotes("Hello.", ["…", "“”"])).toEqual([{ text: "Hello.", quote: false }]);
  });

  it("treats typographic and straight quotes and dashes alike", () => {
    expect(
      highlightQuotes("We can’t sponsor visas — sorry.", ["can't sponsor visas - sorry"]),
    ).toEqual([
      { text: "We ", quote: false },
      { text: "can’t sponsor visas — sorry", quote: true },
      { text: ".", quote: false },
    ]);
  });

  it("merges overlapping quotes and escapes special characters", () => {
    expect(highlightQuotes("Use C++ (senior) and Rust.", ["C++ (senior)", "(senior) and"])).toEqual(
      [
        { text: "Use ", quote: false },
        { text: "C++ (senior) and", quote: true },
        { text: " Rust.", quote: false },
      ],
    );
  });

  it("leaves the text alone when no quote is found", () => {
    expect(highlightQuotes(text, ["Not in the text", "  "])).toEqual([{ text, quote: false }]);
    expect(highlightQuotes("", ["x"])).toEqual([]);
  });
});
