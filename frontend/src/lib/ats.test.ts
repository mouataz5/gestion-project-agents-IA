import { describe, expect, it } from "vitest";

import { runOutcomeMessage } from "./analysis";
import type { ComponentScore, KeywordResult } from "./api/types";
import {
  assessedLabel,
  componentRows,
  gapLabel,
  gapTone,
  iterationStatusLabel,
  keywordGroups,
  keywordPlacement,
  ledgerByPath,
  originLabel,
  originTone,
  scoreSummary,
  scoreTone,
  selectedIteration,
  stopReasonExplanation,
  stopReasonLabel,
  tailoringProblem,
} from "./ats";

function component(name: string, weight: number, score: number | null): ComponentScore {
  return { name, weight, applicable: score !== null, score, details: {} };
}

function keyword(
  term: string,
  status: KeywordResult["status"],
  extra: Partial<KeywordResult> = {},
) {
  return {
    term,
    key: term.toLowerCase(),
    category: "ai_ml",
    importance: "REQUIRED",
    status,
    present: status === "MATCHED" || status === "UNSUPPORTED",
    prominent: false,
    listed: false,
    demonstrated: false,
    supported: status === "MATCHED" || status === "AVAILABLE",
    technical: true,
    score: 0,
    evidence: [],
    ...extra,
  } satisfies KeywordResult;
}

describe("ATS scores", () => {
  it("summarises the score against the master CV", () => {
    expect(scoreSummary({ baseline_score: 82.3, final_score: 88.3, best_iteration: 1 })).toBe(
      "82.3 → 88.3",
    );
    expect(scoreSummary({ baseline_score: 65.7, final_score: 65.7, best_iteration: 0 })).toBe(
      "65.7, your master CV as it is",
    );
    expect(scoreSummary({ baseline_score: 82.3, final_score: null, best_iteration: null })).toBe(
      "82.3 (no CV stored)",
    );
  });

  it("colours a score by the target and the supported ceiling", () => {
    expect(scoreTone(96, 95, 98)).toBe("success");
    expect(scoreTone(88.3, 95, 88.3)).toBe("info"); // as far as the master CV allows
    expect(scoreTone(80, 95, 88.3)).toBe("warning");
    expect(scoreTone(null, 95, 88.3)).toBe("neutral");
  });

  it("says when the posting let the score assess fewer than 100 points", () => {
    expect(assessedLabel(100)).toBeNull();
    expect(assessedLabel(65)).toContain("65 of 100 points");
  });

  it("turns components into rows, redistributing the weights that do not apply", () => {
    const rows = componentRows([
      component("keywords", 30, 0.7273),
      component("skills", 20, 0.4286),
      component("experience", 15, null),
      component("responsibilities", 15, null),
      component("title", 10, 0.7333),
      component("education", 5, null),
      component("formatting", 5, 1),
    ]);

    expect(rows.map((row) => row.label)).toEqual([
      "Job keywords",
      "Skills listed and shown",
      "Years of experience",
      "Responsibilities covered",
      "Job title",
      "Education",
      "ATS-friendly structure",
    ]);
    expect(rows[0]).toMatchObject({ percent: 73, points: 33.6 }); // 30/65 of the score
    expect(rows[2]).toMatchObject({ percent: null, points: null });
    const total = rows.reduce((sum, row) => sum + (row.points ?? 0), 0);
    expect(Math.abs(total - 65.7)).toBeLessThan(0.2); // rows are rounded one by one
  });
});

describe("keywords", () => {
  it("groups keywords by what the master CV backs", () => {
    const groups = keywordGroups([
      keyword("RAG", "MATCHED"),
      keyword("MCP", "AVAILABLE"),
      keyword("Deep Learning", "MISSING"),
    ]);

    expect(groups.matched.map((item) => item.term)).toEqual(["RAG"]);
    expect(groups.available.map((item) => item.term)).toEqual(["MCP"]);
    expect(groups.missing.map((item) => item.term)).toEqual(["Deep Learning"]);
    expect(groups.unsupported).toEqual([]);
  });

  it("says where a matched keyword appears", () => {
    expect(keywordPlacement(keyword("RAG", "MATCHED", { listed: true, demonstrated: true }))).toBe(
      "in your skills and experience",
    );
    expect(
      keywordPlacement(
        keyword("French", "MATCHED", { prominent: true, category: "spoken_language" }),
      ),
    ).toBe("in your languages");
    expect(keywordPlacement(keyword("LLMs", "MATCHED", { prominent: true }))).toBe(
      "in your summary",
    );
  });
});

describe("tailoring outcomes", () => {
  it("labels every stop reason", () => {
    expect(stopReasonLabel("ONLY_UNSUPPORTED_GAINS")).toBe("Only unsupported gains left");
    expect(stopReasonExplanation("ONLY_UNSUPPORTED_GAINS")).toContain("your master CV allows");
    expect(stopReasonLabel("GUARD_REJECTED")).toBe("Rewrites rejected");
  });

  it("explains a tailoring that stored nothing", () => {
    expect(tailoringProblem({ status: "SUCCEEDED", error_code: null, error_message: null })).toBe(
      null,
    );
    expect(
      tailoringProblem({ status: "REFUSED", error_code: "cyber", error_message: null }),
    ).toContain("declined");
    expect(
      tailoringProblem({
        status: "FAILED",
        error_code: "llm_unavailable",
        error_message: "HTTP 529",
      }),
    ).toContain("HTTP 529");
  });

  it("picks the stored version among the iterations", () => {
    const base = { score: 82.3, selected: false };
    expect(
      selectedIteration([
        { ...base, iteration: 0 },
        { ...base, iteration: 1, selected: true },
      ] as never)?.iteration,
    ).toBe(1);
    expect(selectedIteration([{ ...base, iteration: 0 }] as never)?.iteration).toBe(0);
  });

  it("labels gaps, iterations and ledger origins", () => {
    expect(gapLabel("NOT_DEMONSTRATED")).toBe("Listed, never shown in a role");
    expect(gapTone({ kind: "MISSING_KEYWORD", importance: "REQUIRED" })).toBe("danger");
    expect(gapTone({ kind: "MISSING_KEYWORD", importance: "PREFERRED" })).toBe("warning");
    expect(iterationStatusLabel("REPAIRED")).toBe("Scored after repairs");
    expect(originLabel("REWRITTEN")).toBe("Reworded");
    expect(originTone("REVERTED")).toBe("warning");
    const ledger = ledgerByPath([
      { path: "summary", origin: "VERBATIM", sources: [], keywords: [] },
    ]);
    expect(ledger.get("summary")?.origin).toBe("VERBATIM");
  });

  it("names the kind of run in its outcome", () => {
    expect(runOutcomeMessage({ status: "FAILED", events: [] }, "CV generation")).toBe(
      "The CV generation run failed: open the run for details.",
    );
  });
});
