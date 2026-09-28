/**
 * Pure helpers for the master CV pages: client-side file checks, date inputs, list editing and
 * user-facing messages for upload errors.
 */
import type {
  DateRange,
  EducationEntry,
  ExperienceEntry,
  ParsedCV,
  ProjectEntry,
  YearMonth,
} from "@/lib/api/types";

export const CV_EXTENSIONS = [".docx", ".pdf"] as const;
export const DEFAULT_MAX_UPLOAD_MB = 5;

/** Mirrors the backend checks so obvious mistakes are reported before uploading. */
export function checkCvFile(
  file: { name: string; size: number },
  maxBytes: number = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024,
): string | null {
  const name = file.name.toLowerCase();
  if (!CV_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Only .docx and .pdf files are accepted.";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > maxBytes) return `The file is larger than ${formatBytes(maxBytes)}.`;
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const UPLOAD_ERRORS: Record<string, string> = {
  unsupported_file_type: "Only .docx and .pdf files are accepted.",
  file_type_mismatch: "The file content does not match its extension.",
  empty_file: "The file is empty.",
  file_too_large: "The file is too large.",
  unsafe_file: "The file was rejected for safety reasons (archive bomb, encryption or macros).",
  unreadable_file: "The file is corrupt, encrypted or unreadable.",
  too_many_pages: "The document is too long for a CV.",
  no_text_found:
    "No selectable text was found. Scanned CVs are not supported: upload a DOCX or a text-based PDF.",
  payload_too_large: "The file is too large.",
};

export function uploadErrorMessage(code: string | undefined, fallback: string): string {
  return (code && UPLOAD_ERRORS[code]) || fallback;
}

/** "2022-01" (month precision) or "2022" (year precision); "" when unknown. */
export function formatYearMonth(value: YearMonth | null | undefined): string {
  if (!value) return "";
  return value.month ? `${value.year}-${String(value.month).padStart(2, "0")}` : `${value.year}`;
}

export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

function monthYear(value: YearMonth): string {
  return value.month ? `${MONTHS[value.month - 1]} ${value.year}` : `${value.year}`;
}

/** Normalised label for a date range, e.g. "Jan 2022 – present". */
export function dateRangeLabel(dates: DateRange | null | undefined): string {
  if (!dates || (!dates.start && !dates.end && !dates.is_current)) return dates?.text ?? "";
  const start = dates.start ? monthYear(dates.start) : "?";
  if (dates.is_current) return `${start} – present`;
  if (!dates.end || formatYearMonth(dates.end) === formatYearMonth(dates.start)) return start;
  return `${start} – ${monthYear(dates.end)}`;
}

export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length || from === to) return [...items];
  const copy = [...items];
  const [item] = copy.splice(from, 1);
  copy.splice(to, 0, item);
  return copy;
}

export function removeAt<T>(items: readonly T[], index: number): T[] {
  return items.filter((_, position) => position !== index);
}

export function replaceAt<T>(items: readonly T[], index: number, value: T): T[] {
  return items.map((item, position) => (position === index ? value : item));
}

export function emptyExperience(): ExperienceEntry {
  return { title: "", employer: null, location: null, dates: null, bullets: [], details: [] };
}

export function emptyEducation(): EducationEntry {
  return { degree: "", institution: null, location: null, dates: null, bullets: [], details: [] };
}

export function emptyProject(): ProjectEntry {
  return { name: "", dates: null, bullets: [], details: [] };
}

function filled(items: readonly string[]): string[] {
  return items.filter((item) => item.trim() !== "");
}

/** Drop empty rows added in the editor (blank bullets, lines, skills) before saving. */
export function cleanStructure(structure: ParsedCV): ParsedCV {
  const entry = <T extends { bullets: string[]; details: string[] }>(item: T): T => ({
    ...item,
    bullets: filled(item.bullets),
    details: filled(item.details),
  });
  return {
    ...structure,
    summary: structure.summary?.trim() ? structure.summary : null,
    experiences: structure.experiences.map(entry),
    education: structure.education.map(entry),
    projects: structure.projects.map(entry),
    skills: structure.skills.filter((skill) => skill.name.trim() !== ""),
    certifications: filled(structure.certifications),
    languages: filled(structure.languages),
    other_sections: structure.other_sections
      .map((section) => ({ ...section, lines: filled(section.lines) }))
      .filter((section) => section.heading.trim() !== "" || section.lines.length > 0),
  };
}
