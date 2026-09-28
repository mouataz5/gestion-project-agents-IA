import { describe, expect, it } from "vitest";

import {
  checkCvFile,
  dateRangeLabel,
  emptyExperience,
  formatBytes,
  formatYearMonth,
  cleanStructure,
  moveItem,
  removeAt,
  replaceAt,
  uploadErrorMessage,
} from "./cv";

describe("checkCvFile", () => {
  it.each([
    [{ name: "cv.docx", size: 10 }, null],
    [{ name: "CV.PDF", size: 10 }, null],
    [{ name: "cv.doc", size: 10 }, "Only .docx and .pdf files are accepted."],
    [{ name: "cv.docx.exe", size: 10 }, "Only .docx and .pdf files are accepted."],
    [{ name: "cv.pdf", size: 0 }, "The file is empty."],
    [{ name: "cv.pdf", size: 6 * 1024 * 1024 }, "The file is larger than 5.0 MB."],
  ])("%o -> %s", (file, expected) => {
    expect(checkCvFile(file)).toBe(expected);
  });
});

it("formats byte sizes", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(2048)).toBe("2.0 KB");
  expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
});

it("explains upload error codes", () => {
  expect(uploadErrorMessage("file_type_mismatch", "x")).toMatch(/does not match/);
  expect(uploadErrorMessage("something_else", "fallback")).toBe("fallback");
  expect(uploadErrorMessage(undefined, "fallback")).toBe("fallback");
});

describe("year-month inputs", () => {
  it("formats month and year precision", () => {
    expect(formatYearMonth({ year: 2022, month: 1 })).toBe("2022-01");
    expect(formatYearMonth({ year: 2019, month: null })).toBe("2019");
    expect(formatYearMonth(null)).toBe("");
  });
});

describe("dateRangeLabel", () => {
  it("renders normalised ranges", () => {
    expect(
      dateRangeLabel({
        text: "Jan 2022 – Present",
        start: { year: 2022, month: 1 },
        end: null,
        is_current: true,
      }),
    ).toBe("Jan 2022 – present");
    expect(
      dateRangeLabel({
        text: "2017 - 2019",
        start: { year: 2017, month: null },
        end: { year: 2019, month: null },
        is_current: false,
      }),
    ).toBe("2017 – 2019");
    expect(
      dateRangeLabel({
        text: "(2023)",
        start: { year: 2023, month: null },
        end: { year: 2023, month: null },
        is_current: false,
      }),
    ).toBe("2023");
  });

  it("falls back to the original text or nothing", () => {
    expect(dateRangeLabel({ text: "summer", start: null, end: null, is_current: false })).toBe(
      "summer",
    );
    expect(dateRangeLabel(null)).toBe("");
  });
});

describe("list helpers", () => {
  it("moves, removes and replaces items immutably", () => {
    const items = ["a", "b", "c"];
    expect(moveItem(items, 0, 2)).toEqual(["b", "c", "a"]);
    expect(moveItem(items, 0, -1)).toEqual(items);
    expect(removeAt(items, 1)).toEqual(["a", "c"]);
    expect(replaceAt(items, 1, "x")).toEqual(["a", "x", "c"]);
    expect(items).toEqual(["a", "b", "c"]);
  });

  it("creates empty entries", () => {
    expect(emptyExperience()).toEqual({
      title: "",
      employer: null,
      location: null,
      dates: null,
      bullets: [],
      details: [],
    });
  });
});

it("drops empty rows before saving", () => {
  const cleaned = cleanStructure({
    parser_version: "1.0",
    language: "en",
    header_lines: [],
    contact: { emails: [], phones: [], links: [] },
    summary: "  ",
    experiences: [{ ...emptyExperience(), title: "Engineer", bullets: ["Built X.", " "] }],
    education: [],
    projects: [],
    skills: [
      { name: "Python", category: null },
      { name: " ", category: "ML" },
    ],
    certifications: [""],
    languages: ["English", ""],
    other_sections: [
      { heading: "", lines: [""] },
      { heading: "Interests", lines: ["Chess", ""] },
    ],
    warnings: [],
  });

  expect(cleaned.summary).toBeNull();
  expect(cleaned.experiences[0].bullets).toEqual(["Built X."]);
  expect(cleaned.skills).toEqual([{ name: "Python", category: null }]);
  expect(cleaned.certifications).toEqual([]);
  expect(cleaned.languages).toEqual(["English"]);
  expect(cleaned.other_sections).toEqual([{ heading: "Interests", lines: ["Chess"] }]);
});
