"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { Button, Field, Notice, SelectInput, TextArea, TextInput } from "@/components/form";
import { Card } from "@/components/ui";
import type {
  ApiErrorResponse,
  CvVersionDetail,
  DateRange,
  ParsedCV,
  YearMonth,
} from "@/lib/api/types";
import {
  MONTHS,
  cleanStructure,
  emptyEducation,
  emptyExperience,
  emptyProject,
  moveItem,
  removeAt,
  replaceAt,
} from "@/lib/cv";
import { fieldErrors, setIn } from "@/lib/profile";

type Notification = { tone: "success" | "error" | "warning"; message: string };

const SMALL_LABEL = "mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400";

/**
 * Review and correct a parsed CV draft, then confirm it as the master CV. Only the user's own
 * corrections are saved: nothing is generated here.
 */
export function CvDraftEditor({ version }: { version: CvVersionDetail }) {
  const router = useRouter();
  const [structure, setStructure] = useState<ParsedCV>(version.structure);
  const [savedJson, setSavedJson] = useState(() => JSON.stringify(version.structure));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notification, setNotification] = useState<Notification | null>(null);
  const [busy, setBusy] = useState<"save" | "confirm" | null>(null);

  const dirty = JSON.stringify(structure) !== savedJson;
  const base = `/api/backend/candidate/master-cv/${version.id}`;

  function update(path: string, value: unknown) {
    setStructure((current) => setIn(current, path, value));
  }

  function errorFor(path: string): string | undefined {
    return errors[path];
  }

  async function report(response: Response, prefix: readonly string[]) {
    const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
    setErrors(fieldErrors(body?.error?.details, prefix));
    setNotification({
      tone: "error",
      message: body?.error?.message ?? `Request failed (HTTP ${response.status})`,
    });
  }

  /** Save the draft; returns false (and shows why) when the backend rejects it. */
  async function persist(): Promise<boolean> {
    const response = await fetch(`${base}/structure`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(cleanStructure(structure)),
    });
    if (!response.ok) {
      await report(response, ["body"]);
      return false;
    }
    const detail = (await response.json()) as CvVersionDetail;
    setStructure(detail.structure);
    setSavedJson(JSON.stringify(detail.structure));
    setErrors({});
    return true;
  }

  async function save() {
    setBusy("save");
    setNotification(null);
    try {
      if (await persist()) {
        setNotification({ tone: "success", message: "Draft saved." });
        router.refresh();
      }
    } catch {
      setNotification({ tone: "error", message: "Could not reach the dashboard server." });
    } finally {
      setBusy(null);
    }
  }

  async function confirmDraft() {
    const question =
      "Confirm this version as your master CV? It becomes the only source of facts for " +
      "tailored CVs and application answers. Confirmed versions are read-only; you can revise " +
      "them later.";
    if (!window.confirm(question)) return;
    setBusy("confirm");
    setNotification(null);
    try {
      if (dirty && !(await persist())) return;
      const response = await fetch(`${base}/confirm`, { method: "POST" });
      if (!response.ok) {
        await report(response, []);
        return;
      }
      setNotification({ tone: "success", message: "Confirmed: this is now your master CV." });
      router.refresh();
    } catch {
      setNotification({ tone: "error", message: "Could not reach the dashboard server." });
    } finally {
      setBusy(null);
    }
  }

  const warnings = structure.warnings;

  return (
    <div className="space-y-6" data-testid="cv-editor">
      {warnings.length > 0 && (
        <Notice tone="warning">
          <p className="font-semibold">Review these points before confirming</p>
          <ul className="mt-1 list-disc pl-5" data-testid="cv-warnings">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Notice>
      )}

      <Card title="Summary">
        <TextArea
          aria-label="Summary"
          rows={4}
          value={structure.summary ?? ""}
          onChange={(event) => update("summary", event.target.value)}
        />
      </Card>

      <Card
        title={`Experience (${structure.experiences.length})`}
        action={
          <Button
            variant="secondary"
            small
            onClick={() => update("experiences", [...structure.experiences, emptyExperience()])}
          >
            + Add experience
          </Button>
        }
      >
        <EntryList
          items={structure.experiences}
          empty="No experience entries. Add them manually if the parser missed them."
          label={(item, index) => item.title || `Experience ${index + 1}`}
          onChange={(items) => update("experiences", items)}
          render={(item, index) => {
            const path = `experiences.${index}`;
            return (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Field
                    label="Job title"
                    htmlFor={`${path}.title`}
                    error={errorFor(`${path}.title`)}
                  >
                    <TextInput
                      id={`${path}.title`}
                      value={item.title}
                      invalid={Boolean(errorFor(`${path}.title`))}
                      onChange={(event) => update(`${path}.title`, event.target.value)}
                    />
                  </Field>
                  <Field label="Employer" htmlFor={`${path}.employer`}>
                    <TextInput
                      id={`${path}.employer`}
                      value={item.employer ?? ""}
                      onChange={(event) => update(`${path}.employer`, event.target.value || null)}
                    />
                  </Field>
                  <Field label="Location" htmlFor={`${path}.location`}>
                    <TextInput
                      id={`${path}.location`}
                      value={item.location ?? ""}
                      onChange={(event) => update(`${path}.location`, event.target.value || null)}
                    />
                  </Field>
                </div>
                <DatesEditor
                  path={`${path}.dates`}
                  dates={item.dates}
                  onChange={(dates) => update(`${path}.dates`, dates)}
                  error={errorFor(`${path}.dates`)}
                />
                <StringList
                  label="Bullet points"
                  items={item.bullets}
                  multiline
                  onChange={(bullets) => update(`${path}.bullets`, bullets)}
                />
                <StringList
                  label="Other details"
                  items={item.details}
                  onChange={(details) => update(`${path}.details`, details)}
                />
              </>
            );
          }}
        />
      </Card>

      <Card
        title={`Education (${structure.education.length})`}
        action={
          <Button
            variant="secondary"
            small
            onClick={() => update("education", [...structure.education, emptyEducation()])}
          >
            + Add education
          </Button>
        }
      >
        <EntryList
          items={structure.education}
          empty="No education entries."
          label={(item, index) => item.degree || `Education ${index + 1}`}
          onChange={(items) => update("education", items)}
          render={(item, index) => {
            const path = `education.${index}`;
            return (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Field
                    label="Degree"
                    htmlFor={`${path}.degree`}
                    error={errorFor(`${path}.degree`)}
                  >
                    <TextInput
                      id={`${path}.degree`}
                      value={item.degree}
                      invalid={Boolean(errorFor(`${path}.degree`))}
                      onChange={(event) => update(`${path}.degree`, event.target.value)}
                    />
                  </Field>
                  <Field label="Institution" htmlFor={`${path}.institution`}>
                    <TextInput
                      id={`${path}.institution`}
                      value={item.institution ?? ""}
                      onChange={(event) =>
                        update(`${path}.institution`, event.target.value || null)
                      }
                    />
                  </Field>
                  <Field label="Location" htmlFor={`${path}.location`}>
                    <TextInput
                      id={`${path}.location`}
                      value={item.location ?? ""}
                      onChange={(event) => update(`${path}.location`, event.target.value || null)}
                    />
                  </Field>
                </div>
                <DatesEditor
                  path={`${path}.dates`}
                  dates={item.dates}
                  onChange={(dates) => update(`${path}.dates`, dates)}
                  error={errorFor(`${path}.dates`)}
                />
                <StringList
                  label="Bullet points"
                  items={item.bullets}
                  multiline
                  onChange={(bullets) => update(`${path}.bullets`, bullets)}
                />
                <StringList
                  label="Other details"
                  items={item.details}
                  onChange={(details) => update(`${path}.details`, details)}
                />
              </>
            );
          }}
        />
      </Card>

      <Card
        title={`Projects (${structure.projects.length})`}
        action={
          <Button
            variant="secondary"
            small
            onClick={() => update("projects", [...structure.projects, emptyProject()])}
          >
            + Add project
          </Button>
        }
      >
        <EntryList
          items={structure.projects}
          empty="No projects."
          label={(item, index) => item.name || `Project ${index + 1}`}
          onChange={(items) => update("projects", items)}
          render={(item, index) => {
            const path = `projects.${index}`;
            return (
              <>
                <Field
                  label="Project name"
                  htmlFor={`${path}.name`}
                  error={errorFor(`${path}.name`)}
                >
                  <TextInput
                    id={`${path}.name`}
                    value={item.name}
                    invalid={Boolean(errorFor(`${path}.name`))}
                    onChange={(event) => update(`${path}.name`, event.target.value)}
                  />
                </Field>
                <DatesEditor
                  path={`${path}.dates`}
                  dates={item.dates}
                  onChange={(dates) => update(`${path}.dates`, dates)}
                  error={errorFor(`${path}.dates`)}
                />
                <StringList
                  label="Bullet points"
                  items={item.bullets}
                  multiline
                  onChange={(bullets) => update(`${path}.bullets`, bullets)}
                />
                <StringList
                  label="Other details"
                  items={item.details}
                  onChange={(details) => update(`${path}.details`, details)}
                />
              </>
            );
          }}
        />
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card
          title={`Skills (${structure.skills.length})`}
          action={
            <Button
              variant="secondary"
              small
              onClick={() => update("skills", [...structure.skills, { name: "", category: null }])}
            >
              + Add skill
            </Button>
          }
        >
          {structure.skills.length === 0 && (
            <p className="text-sm text-slate-500">No skills section was found.</p>
          )}
          <ul className="space-y-1.5">
            {structure.skills.map((skill, index) => (
              <li key={index} className="flex items-center gap-2">
                <TextInput
                  aria-label={`Skill ${index + 1}`}
                  value={skill.name}
                  onChange={(event) => update(`skills.${index}.name`, event.target.value)}
                />
                <TextInput
                  aria-label={`Skill ${index + 1} category`}
                  placeholder="Category"
                  inline
                  className="w-40 shrink-0"
                  value={skill.category ?? ""}
                  onChange={(event) =>
                    update(`skills.${index}.category`, event.target.value || null)
                  }
                />
                <Button
                  variant="ghost"
                  small
                  aria-label={`Remove skill ${index + 1}`}
                  onClick={() => update("skills", removeAt(structure.skills, index))}
                >
                  ×
                </Button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-6">
          <Card title="Certifications">
            <StringList
              label="Certifications"
              hideLabel
              items={structure.certifications}
              onChange={(items) => update("certifications", items)}
            />
          </Card>
          <Card title="Languages">
            <StringList
              label="Languages"
              hideLabel
              items={structure.languages}
              onChange={(items) => update("languages", items)}
            />
          </Card>
        </div>
      </div>

      <Card
        title="Other sections"
        action={
          <Button
            variant="secondary"
            small
            onClick={() =>
              update("other_sections", [...structure.other_sections, { heading: "", lines: [] }])
            }
          >
            + Add section
          </Button>
        }
      >
        {structure.other_sections.length === 0 && <p className="text-sm text-slate-500">None.</p>}
        <div className="space-y-4">
          {structure.other_sections.map((section, index) => (
            <div
              key={index}
              className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
            >
              <div className="mb-2 flex items-center gap-2">
                <TextInput
                  aria-label={`Section ${index + 1} heading`}
                  value={section.heading}
                  onChange={(event) =>
                    update(`other_sections.${index}.heading`, event.target.value)
                  }
                />
                <Button
                  variant="ghost"
                  small
                  className="shrink-0 whitespace-nowrap"
                  onClick={() =>
                    update("other_sections", removeAt(structure.other_sections, index))
                  }
                >
                  Remove section
                </Button>
              </div>
              <StringList
                label="Lines"
                items={section.lines}
                onChange={(lines) => update(`other_sections.${index}.lines`, lines)}
              />
            </div>
          ))}
        </div>
      </Card>

      <Card title="Detected header & contact">
        <p className="mb-2 text-xs text-slate-500">
          Read-only: your contact details for applications are managed on the Candidate page.
        </p>
        <ul className="space-y-0.5 text-sm">
          {structure.header_lines.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      </Card>

      <div className="sticky bottom-0 z-10 -mx-6 border-t border-slate-200 bg-white/90 px-6 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        {notification && (
          <div className="mb-3">
            <Notice tone={notification.tone}>{notification.message}</Notice>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void save()} disabled={busy !== null || !dirty}>
            {busy === "save" ? "Saving…" : "Save draft"}
          </Button>
          <Button
            variant="secondary"
            disabled={busy !== null || !dirty}
            onClick={() => {
              setStructure(JSON.parse(savedJson) as ParsedCV);
              setErrors({});
              setNotification(null);
            }}
          >
            Discard changes
          </Button>
          <span className="text-xs text-slate-500">
            {dirty ? "Unsaved changes" : "All changes saved"}
          </span>
          <Button
            className="ml-auto"
            onClick={() => void confirmDraft()}
            disabled={busy !== null}
            data-testid="confirm-cv"
          >
            {busy === "confirm" ? "Confirming…" : "Confirm as master CV"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function EntryList<T>({
  items,
  render,
  label,
  onChange,
  empty,
}: {
  items: readonly T[];
  render: (item: T, index: number) => ReactNode;
  label: (item: T, index: number) => string;
  onChange: (items: T[]) => void;
  empty: string;
}) {
  if (items.length === 0) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ol className="space-y-4">
      {items.map((item, index) => (
        <li
          key={index}
          className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-semibold">{label(item, index)}</p>
            <div className="flex shrink-0 gap-1">
              <Button
                variant="ghost"
                small
                aria-label="Move up"
                disabled={index === 0}
                onClick={() => onChange(moveItem(items, index, index - 1))}
              >
                ↑
              </Button>
              <Button
                variant="ghost"
                small
                aria-label="Move down"
                disabled={index === items.length - 1}
                onClick={() => onChange(moveItem(items, index, index + 1))}
              >
                ↓
              </Button>
              <Button variant="ghost" small onClick={() => onChange(removeAt(items, index))}>
                Remove
              </Button>
            </div>
          </div>
          {render(item, index)}
        </li>
      ))}
    </ol>
  );
}

function StringList({
  label,
  items,
  onChange,
  multiline = false,
  hideLabel = false,
}: {
  label: string;
  items: readonly string[];
  onChange: (items: string[]) => void;
  multiline?: boolean;
  hideLabel?: boolean;
}) {
  return (
    <div>
      {!hideLabel && <p className={SMALL_LABEL}>{label}</p>}
      <ul className="space-y-1.5">
        {items.map((item, index) => (
          <li key={index} className="flex items-start gap-2">
            {multiline ? (
              <TextArea
                aria-label={`${label} ${index + 1}`}
                rows={2}
                value={item}
                onChange={(event) => onChange(replaceAt(items, index, event.target.value))}
              />
            ) : (
              <TextInput
                aria-label={`${label} ${index + 1}`}
                value={item}
                onChange={(event) => onChange(replaceAt(items, index, event.target.value))}
              />
            )}
            <Button
              variant="ghost"
              small
              aria-label={`Remove ${label.toLowerCase()} ${index + 1}`}
              onClick={() => onChange(removeAt(items, index))}
            >
              ×
            </Button>
          </li>
        ))}
      </ul>
      <Button variant="ghost" small className="mt-1" onClick={() => onChange([...items, ""])}>
        + Add
      </Button>
    </div>
  );
}

const NO_DATES: DateRange = { text: "", start: null, end: null, is_current: false };

function DatesEditor({
  path,
  dates,
  onChange,
  error,
}: {
  path: string;
  dates: DateRange | null;
  onChange: (dates: DateRange | null) => void;
  error?: string;
}) {
  const value = dates ?? NO_DATES;

  function set(patch: Partial<DateRange>) {
    const next = { ...value, ...patch };
    const empty = !next.text && !next.start && !next.end && !next.is_current;
    onChange(empty ? null : next);
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-end">
        <Field label="Dates as written" htmlFor={`${path}.text`}>
          <TextInput
            id={`${path}.text`}
            value={value.text}
            onChange={(event) => set({ text: event.target.value })}
          />
        </Field>
        <YearMonthInput label="Start" value={value.start} onChange={(start) => set({ start })} />
        <YearMonthInput
          label="End"
          value={value.end}
          disabled={value.is_current}
          onChange={(end) => set({ end })}
        />
        <label className="inline-flex items-center gap-1.5 pb-2 text-sm">
          <input
            type="checkbox"
            checked={value.is_current}
            onChange={(event) =>
              set({
                is_current: event.target.checked,
                end: event.target.checked ? null : value.end,
              })
            }
          />
          Current
        </label>
      </div>
      {error && (
        <p role="alert" className="mt-1 text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
    </div>
  );
}

function YearMonthInput({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: YearMonth | null;
  onChange: (value: YearMonth | null) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset disabled={disabled}>
      <legend className={SMALL_LABEL}>{label}</legend>
      <div className="flex gap-1">
        <SelectInput
          aria-label={`${label} month`}
          inline
          className="w-20"
          value={value?.month ?? ""}
          disabled={disabled || value === null}
          onChange={(event) =>
            value &&
            onChange({ ...value, month: event.target.value ? Number(event.target.value) : null })
          }
        >
          <option value="">—</option>
          {MONTHS.map((month, index) => (
            <option key={month} value={index + 1}>
              {month}
            </option>
          ))}
        </SelectInput>
        <TextInput
          aria-label={`${label} year`}
          type="number"
          min={1900}
          max={2100}
          placeholder="Year"
          inline
          className="w-24"
          value={value?.year ?? ""}
          onChange={(event) =>
            onChange(
              event.target.value === ""
                ? null
                : { year: Number(event.target.value), month: value?.month ?? null },
            )
          }
        />
      </div>
    </fieldset>
  );
}
