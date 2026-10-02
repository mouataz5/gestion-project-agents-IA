import { describe, expect, it } from "vitest";

import type { CompanyRead } from "@/lib/api/types";

import {
  checkTone,
  companyCreateBody,
  companyToForm,
  companyUpdateBody,
  emptyCompanyForm,
} from "./companies";

const NOVA: CompanyRead = {
  id: "7b0c1f7e-0000-4000-8000-000000000001",
  name: "Nova AI",
  career_url: "https://nova-ai.example/careers",
  country: "France",
  country_code: "FR",
  ats_type: "GREENHOUSE",
  board_token: "nova-ai",
  target_roles: ["AI Engineer"],
  enabled: true,
  notes: null,
  last_checked_at: null,
  last_check_status: null,
  job_count: 3,
  created_at: "2026-10-02T08:00:00Z",
  updated_at: "2026-10-02T08:00:00Z",
};

describe("company form", () => {
  it("builds a clean create body", () => {
    const body = companyCreateBody({
      ...emptyCompanyForm(),
      name: "  Orion Labs ",
      career_url: " https://orion.example/careers ",
      country_code: "fr",
      board_token: " ",
      target_roles: [" AI Engineer ", ""],
      notes: "",
    });

    expect(body).toEqual({
      name: "Orion Labs",
      career_url: "https://orion.example/careers",
      country_code: "FR",
      ats_type: "GENERIC",
      board_token: null,
      target_roles: ["AI Engineer"],
      enabled: true,
      notes: null,
    });
  });

  it("sends only the changed fields", () => {
    const form = companyToForm(NOVA);
    expect(companyUpdateBody(NOVA, form)).toEqual({});

    expect(
      companyUpdateBody(NOVA, {
        ...form,
        enabled: false,
        notes: "Paused",
        target_roles: [...form.target_roles, "LLM Engineer"],
      }),
    ).toEqual({ enabled: false, notes: "Paused", target_roles: ["AI Engineer", "LLM Engineer"] });
    expect(companyUpdateBody(NOVA, { ...form, board_token: "", country_code: "" })).toEqual({
      board_token: null,
      country_code: null,
    });
  });

  it("colours the last board check", () => {
    expect(checkTone("ok: 4 postings")).toBe("success");
    expect(checkTone("error: board unavailable")).toBe("danger");
    expect(checkTone(null)).toBe("neutral");
  });
});
