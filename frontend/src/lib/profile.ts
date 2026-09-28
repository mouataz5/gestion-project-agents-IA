/**
 * Pure helpers for the candidate profile editor: immutable nested updates, tag parsing,
 * API validation errors mapped to field paths, and labels for fields that need user input.
 */

/** Immutable update of a nested value addressed by a dotted path ("identity.location.city"). */
export function setIn<T>(target: T, path: string, value: unknown): T {
  const [head, ...rest] = path.split(".");
  const source: unknown = target ?? {};
  if (Array.isArray(source)) {
    const index = Number(head);
    const copy = [...source];
    copy[index] = rest.length ? setIn(copy[index], rest.join("."), value) : value;
    return copy as T;
  }
  const record = source as Record<string, unknown>;
  return {
    ...record,
    [head]: rest.length ? setIn(record[head], rest.join("."), value) : value,
  } as T;
}

export function getIn(target: unknown, path: string): unknown {
  let current: unknown = target;
  for (const part of path.split(".")) {
    if (current === null || current === undefined) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/** Split free text into tags (comma or newline separated), trimmed and de-duplicated. */
export function parseTags(text: string): string[] {
  return addTags([], text);
}

/** Append tags parsed from ``text`` unless already present (case-insensitive). */
export function addTags(tags: readonly string[], text: string): string[] {
  const result = [...tags];
  const seen = new Set(tags.map((tag) => tag.toLowerCase()));
  for (const raw of text.split(/[,\n]/)) {
    const tag = raw.trim().replace(/\s+/g, " ");
    if (tag && !seen.has(tag.toLowerCase())) {
      seen.add(tag.toLowerCase());
      result.push(tag);
    }
  }
  return result;
}

/** "" -> null, otherwise the trimmed text (optional text fields are null when empty). */
export function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Empty lists become null: for nullable list fields, empty means "not provided yet". */
export function emptyToNull<T>(items: readonly T[] | null | undefined): T[] | null {
  return items && items.length > 0 ? [...items] : null;
}

export type Tristate = "yes" | "no" | "unknown";

export function toTristate(value: boolean | null | undefined): Tristate {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "unknown";
}

export function fromTristate(value: string): boolean | null {
  if (value === "yes") return true;
  if (value === "no") return false;
  return null;
}

interface ValidationDetail {
  loc?: unknown;
  msg?: unknown;
}

/**
 * Field errors from an API error envelope, keyed by dotted profile path. Handles request
 * validation locations (["body", "profile", "identity", "fullname"]) and service errors that
 * already use dotted strings ("identity.fullname").
 */
export function fieldErrors(details: unknown, prefix: readonly string[] = ["body", "profile"]) {
  const errors: Record<string, string> = {};
  if (!Array.isArray(details)) return errors;
  for (const item of details as ValidationDetail[]) {
    let parts: string[];
    if (Array.isArray(item.loc)) parts = item.loc.map(String);
    else if (typeof item.loc === "string") parts = item.loc.split(".");
    else continue;
    let start = 0;
    while (start < prefix.length && parts[start] === prefix[start]) start += 1;
    const path = parts.slice(start).join(".");
    if (path && !(path in errors))
      errors[path] = typeof item.msg === "string" ? item.msg : "Invalid";
  }
  return errors;
}

export const FIELD_LABELS: Record<string, string> = {
  "contact.email": "Email",
  "contact.phone": "Phone",
  "identity.location.country_code": "Country code",
  "work_authorization.visa_sponsorship_required": "Visa sponsorship required",
  "relocation.willing_to_relocate": "Willing to relocate",
  "targets.roles": "Target roles",
  "targets.countries.primary": "Primary target countries",
  "application_defaults.notice_period": "Notice period",
  "application_defaults.salary_expectations": "Salary expectations",
  "application_defaults.earliest_start_date": "Earliest start date",
  "application_defaults.languages": "Spoken languages",
  "application_defaults.preferred_work_modes": "Preferred work modes",
};

export function fieldLabel(path: string): string {
  return FIELD_LABELS[path] ?? path;
}
