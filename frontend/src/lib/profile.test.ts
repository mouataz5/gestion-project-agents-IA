import { describe, expect, it } from "vitest";

import {
  addTags,
  blankToNull,
  emptyToNull,
  fieldErrors,
  fieldLabel,
  fromTristate,
  getIn,
  parseTags,
  setIn,
  toTristate,
} from "./profile";

describe("setIn / getIn", () => {
  it("updates a nested value without mutating the original", () => {
    const original = { identity: { full_name: "A", location: { city: "Tunis" } }, other: 1 };

    const updated = setIn(original, "identity.location.city", "Paris");

    expect(updated.identity.location.city).toBe("Paris");
    expect(updated.identity.full_name).toBe("A");
    expect(original.identity.location.city).toBe("Tunis");
    expect(updated.other).toBe(1);
  });

  it("updates array items by index", () => {
    const updated = setIn({ items: [{ a: 1 }, { a: 2 }] }, "items.1.a", 3);
    expect(updated.items).toEqual([{ a: 1 }, { a: 3 }]);
  });

  it("creates missing branches and reads nested values", () => {
    const updated = setIn({} as Record<string, unknown>, "contact.email", "x@example.com");
    expect(getIn(updated, "contact.email")).toBe("x@example.com");
    expect(getIn(updated, "contact.phone")).toBeUndefined();
    expect(getIn(null, "a.b")).toBeUndefined();
  });
});

describe("tags", () => {
  it("parses comma and newline separated tags without duplicates", () => {
    expect(parseTags(" AI Engineer, LLM  Engineer\nai engineer,, ")).toEqual([
      "AI Engineer",
      "LLM Engineer",
    ]);
  });

  it("appends only new tags", () => {
    expect(addTags(["Python"], "python, Docker")).toEqual(["Python", "Docker"]);
  });
});

describe("value conversions", () => {
  it("maps blank text and empty lists to null", () => {
    expect(blankToNull("  ")).toBeNull();
    expect(blankToNull(" 1 month ")).toBe("1 month");
    expect(emptyToNull([])).toBeNull();
    expect(emptyToNull(undefined)).toBeNull();
    expect(emptyToNull(["remote"])).toEqual(["remote"]);
  });

  it("converts tri-state booleans", () => {
    expect([true, false, null].map(toTristate)).toEqual(["yes", "no", "unknown"]);
    expect(["yes", "no", "unknown"].map(fromTristate)).toEqual([true, false, null]);
  });
});

describe("fieldErrors", () => {
  it("maps request validation locations to profile paths", () => {
    const errors = fieldErrors([
      { loc: ["body", "profile", "identity", "fullname"], msg: "Extra inputs are not permitted" },
      { loc: ["body", "profile_version"], msg: "Field required" },
    ]);
    expect(errors).toEqual({
      "identity.fullname": "Extra inputs are not permitted",
      profile_version: "Field required",
    });
  });

  it("accepts dotted string locations and ignores malformed details", () => {
    expect(fieldErrors([{ loc: "experiences.0.title", msg: "A job title is required" }])).toEqual({
      "experiences.0.title": "A job title is required",
    });
    expect(fieldErrors(null)).toEqual({});
    expect(fieldErrors([{ msg: "no location" }])).toEqual({});
  });
});

it("labels fields that need user input", () => {
  expect(fieldLabel("application_defaults.notice_period")).toBe("Notice period");
  expect(fieldLabel("unknown.path")).toBe("unknown.path");
});
