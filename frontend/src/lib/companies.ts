/**
 * Pure helpers for the company watchlist: form state, request bodies (create and partial
 * update) and the tone of the last board check.
 */
import type { CompanyAtsType, CompanyCreate, CompanyRead, CompanyUpdate } from "@/lib/api/types";
import type { Tone } from "@/lib/format";

export interface CompanyForm {
  name: string;
  career_url: string;
  country_code: string;
  ats_type: CompanyAtsType;
  board_token: string;
  target_roles: string[];
  enabled: boolean;
  notes: string;
}

export function emptyCompanyForm(): CompanyForm {
  return {
    name: "",
    career_url: "",
    country_code: "",
    ats_type: "GENERIC",
    board_token: "",
    target_roles: [],
    enabled: true,
    notes: "",
  };
}

export function companyToForm(company: CompanyRead): CompanyForm {
  return {
    name: company.name,
    career_url: company.career_url,
    country_code: company.country_code ?? "",
    ats_type: company.ats_type as CompanyAtsType,
    board_token: company.board_token ?? "",
    target_roles: [...company.target_roles],
    enabled: company.enabled,
    notes: company.notes ?? "",
  };
}

function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function companyCreateBody(form: CompanyForm): CompanyCreate {
  return {
    name: form.name.trim(),
    career_url: form.career_url.trim(),
    country_code: blankToNull(form.country_code)?.toUpperCase() ?? null,
    ats_type: form.ats_type,
    board_token: blankToNull(form.board_token),
    target_roles: form.target_roles.map((role) => role.trim()).filter(Boolean),
    enabled: form.enabled,
    notes: blankToNull(form.notes),
  };
}

/** Only the fields that changed (an empty body means nothing to save). */
export function companyUpdateBody(original: CompanyRead, form: CompanyForm): CompanyUpdate {
  const next = companyCreateBody(form);
  const body: CompanyUpdate = {};
  if (next.name !== original.name) body.name = next.name;
  if (next.career_url !== original.career_url) body.career_url = next.career_url;
  if ((next.country_code ?? null) !== original.country_code) body.country_code = next.country_code;
  if (next.ats_type !== original.ats_type) body.ats_type = next.ats_type;
  if ((next.board_token ?? null) !== original.board_token) body.board_token = next.board_token;
  if (JSON.stringify(next.target_roles) !== JSON.stringify(original.target_roles)) {
    body.target_roles = next.target_roles;
  }
  if (next.enabled !== original.enabled) body.enabled = next.enabled;
  if ((next.notes ?? null) !== original.notes) body.notes = next.notes;
  return body;
}

/** "ok: 4 postings" → success, "error: …" → danger, never checked → neutral. */
export function checkTone(status: string | null | undefined): Tone {
  if (!status) return "neutral";
  if (status.startsWith("ok")) return "success";
  return status.startsWith("error") ? "danger" : "warning";
}
