export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

const TONES: Record<string, Tone> = {
  ok: "success",
  succeeded: "success",
  degraded: "warning",
  partial_success: "warning",
  warning: "warning",
  down: "danger",
  failed: "danger",
  error: "danger",
  running: "info",
  pending: "info",
  info: "info",
  cancelled: "neutral",
  // Master CV versions: a parsed draft needs review; confirmed is the active master CV.
  parsed: "warning",
  confirmed: "success",
  superseded: "neutral",
  // Tailored CVs: the current version of an application.
  generated: "success",
  // Skill evidence strength.
  demonstrated: "success",
  listed: "info",
  none: "warning",
};

export function statusTone(status: string): Tone {
  return TONES[status.toLowerCase()] ?? "neutral";
}

const ACRONYMS: Record<string, string> = {
  api: "API",
  ats: "ATS",
  cv: "CV",
  id: "ID",
  linkedin: "LinkedIn",
  llm: "LLM",
  smartrecruiters: "SmartRecruiters",
  url: "URL",
};

export function humanize(value: string): string {
  const words = value.replace(/[._]+/g, " ").trim().toLowerCase().split(/\s+/);
  const text = words.map((word) => ACRONYMS[word] ?? word).join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
  }
  const hours = Math.floor(seconds / 3600);
  return `${hours} h ${Math.floor((seconds - hours * 3600) / 60)} min`;
}

/** `YYYY-MM-DD HH:MM:SS` in the given IANA time zone (numeric parts only: locale-independent). */
export function formatDateTime(iso: string | null | undefined, timeZone = "UTC"): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

export function formatRelative(iso: string, now: Date = new Date()): string {
  const deltaSeconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  const future = deltaSeconds < 0;
  const seconds = Math.abs(deltaSeconds);
  if (seconds < 5) return "just now";
  let amount: string;
  if (seconds < 60) amount = `${seconds} s`;
  else if (seconds < 3600) amount = `${Math.floor(seconds / 60)} min`;
  else if (seconds < 86400) amount = `${Math.floor(seconds / 3600)} h`;
  else amount = `${Math.floor(seconds / 86400)} d`;
  return future ? `in ${amount}` : `${amount} ago`;
}
