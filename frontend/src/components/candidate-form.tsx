"use client";

import { useRouter } from "next/navigation";
import { type ChangeEvent, type ReactNode, useState } from "react";

import {
  Button,
  Field,
  Notice,
  SelectInput,
  TextInput,
  buttonClass,
  controlClass,
} from "@/components/form";
import { TagInput } from "@/components/tag-input";
import { Card } from "@/components/ui";
import {
  AUTHORIZATION_STATUSES,
  LANGUAGE_LEVELS,
  WORK_MODES,
  type ApiErrorResponse,
  type AuthorizationStatus,
  type CandidateProfile,
  type CandidateRead,
  type CandidateSkill,
  type LanguageLevel,
  type SalaryExpectation,
  type SkillStrength,
  type TargetCountry,
  type WorkMode,
} from "@/lib/api/types";
import { removeAt, replaceAt } from "@/lib/cv";
import { humanize } from "@/lib/format";
import {
  emptyToNull,
  fieldErrors,
  fieldLabel,
  fromTristate,
  setIn,
  toTristate,
} from "@/lib/profile";

type Notification = { tone: "success" | "error" | "warning"; message: string; conflict?: boolean };

const STRENGTH_DOT: Record<SkillStrength, string> = {
  DEMONSTRATED: "bg-emerald-500",
  LISTED: "bg-sky-500",
  NONE: "bg-amber-500",
};

const SMALL_LABEL = "mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400";

export function CandidateProfileForm({
  initial,
  skills,
}: {
  initial: CandidateRead;
  skills: readonly CandidateSkill[];
}) {
  const router = useRouter();
  const [saved, setSaved] = useState(initial);
  const [profile, setProfile] = useState<CandidateProfile>(initial.profile);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notification, setNotification] = useState<Notification | null>(null);
  const [busy, setBusy] = useState<"save" | "import" | null>(null);

  const dirty = JSON.stringify(profile) !== JSON.stringify(saved.profile);
  const needs = new Set(saved.needs_user_input);
  const strengths = new Map(skills.map((skill) => [skill.name.toLowerCase(), skill.strength]));

  function update(path: string, value: unknown) {
    setProfile((current) => setIn(current, path, value));
  }

  /** Optional text: an empty input means "unknown" (null). */
  function optionalText(path: string) {
    return (event: ChangeEvent<HTMLInputElement>) =>
      update(path, event.target.value === "" ? null : event.target.value);
  }

  function errorFor(path: string): string | undefined {
    return errors[path];
  }

  function errorsUnder(path: string): string | undefined {
    const entries = Object.entries(errors).filter(([key]) => key.startsWith(`${path}.`));
    return entries.length ? entries.map(([key, msg]) => `${key}: ${msg}`).join(" · ") : undefined;
  }

  function accept(result: CandidateRead, message: string) {
    setSaved(result);
    setProfile(result.profile);
    setErrors({});
    setNotification({ tone: "success", message });
    router.refresh(); // skill evidence and other server-rendered parts
  }

  async function failure(response: Response) {
    const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
    const message = body?.error?.message ?? `Request failed (HTTP ${response.status})`;
    if (response.status === 409) {
      setNotification({ tone: "warning", message, conflict: true });
    } else {
      setErrors(fieldErrors(body?.error?.details));
      setNotification({ tone: "error", message });
    }
  }

  async function save() {
    setBusy("save");
    setNotification(null);
    try {
      const response = await fetch("/api/backend/candidate", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ profile_version: saved.profile_version, profile }),
      });
      if (!response.ok) return await failure(response);
      accept((await response.json()) as CandidateRead, "Profile saved.");
    } catch {
      setNotification({ tone: "error", message: "Could not reach the dashboard server." });
    } finally {
      setBusy(null);
    }
  }

  async function reimport() {
    const question =
      "Reload the profile from candidate/profile.yaml (and profile.local.yaml)? " +
      "Changes made here since the last import are replaced.";
    if (!window.confirm(question)) return;
    setBusy("import");
    setNotification(null);
    try {
      const response = await fetch("/api/backend/candidate/import", { method: "POST" });
      if (!response.ok) return await failure(response);
      accept((await response.json()) as CandidateRead, "Profile imported from the YAML files.");
    } catch {
      setNotification({ tone: "error", message: "Could not reach the dashboard server." });
    } finally {
      setBusy(null);
    }
  }

  const identity = profile.identity;
  const location = identity.location;
  const contact = profile.contact;
  const authorization = profile.work_authorization;
  const defaults = profile.application_defaults;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="space-y-6"
      aria-label="Candidate profile"
    >
      {needs.size > 0 && (
        <Notice tone="warning">
          <p className="font-semibold">
            {needs.size} field{needs.size === 1 ? "" : "s"} need your input
          </p>
          <p className="mt-1">
            {[...needs].map(fieldLabel).join(", ")}. These values are never guessed: application
            questions that depend on them are marked NEEDS_USER_INPUT until you fill them in.
          </p>
        </Notice>
      )}

      <Card title="Identity">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label="Full name"
            htmlFor="identity-full-name"
            error={errorFor("identity.full_name")}
          >
            <TextInput
              id="identity-full-name"
              required
              value={identity.full_name}
              onChange={(event) => update("identity.full_name", event.target.value)}
              invalid={Boolean(errorFor("identity.full_name"))}
            />
          </Field>
          <Field label="Headline" htmlFor="identity-headline" error={errorFor("identity.headline")}>
            <TextInput
              id="identity-headline"
              value={identity.headline ?? ""}
              onChange={optionalText("identity.headline")}
            />
          </Field>
          <Field
            label="Nationality"
            htmlFor="identity-nationality"
            error={errorFor("identity.nationality")}
          >
            <TextInput
              id="identity-nationality"
              value={identity.nationality ?? ""}
              onChange={optionalText("identity.nationality")}
            />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="City" htmlFor="identity-city" className="col-span-1">
              <TextInput
                id="identity-city"
                value={location.city ?? ""}
                onChange={optionalText("identity.location.city")}
              />
            </Field>
            <Field label="Country" htmlFor="identity-country" className="col-span-1">
              <TextInput
                id="identity-country"
                value={location.country ?? ""}
                onChange={optionalText("identity.location.country")}
              />
            </Field>
            <Field
              label="Code"
              htmlFor="identity-country-code"
              className="col-span-1"
              needsInput={needs.has("identity.location.country_code")}
              error={errorFor("identity.location.country_code")}
            >
              <TextInput
                id="identity-country-code"
                maxLength={2}
                placeholder="TN"
                value={location.country_code ?? ""}
                onChange={(event) =>
                  update(
                    "identity.location.country_code",
                    event.target.value === "" ? null : event.target.value.toUpperCase(),
                  )
                }
                invalid={Boolean(errorFor("identity.location.country_code"))}
              />
            </Field>
          </div>
        </div>
      </Card>

      <Card title="Contact (private)">
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Stored in the local database only: never committed to Git and left out of exports unless
          you explicitly include private details.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {(
            [
              ["email", "Email", "email"],
              ["phone", "Phone", "tel"],
              ["address", "Address", "text"],
              ["linkedin_url", "LinkedIn URL", "url"],
              ["github_url", "GitHub URL", "url"],
              ["portfolio_url", "Portfolio URL", "url"],
            ] as const
          ).map(([key, label, type]) => (
            <Field
              key={key}
              label={label}
              htmlFor={`contact-${key}`}
              needsInput={needs.has(`contact.${key}`)}
              error={errorFor(`contact.${key}`)}
            >
              <TextInput
                id={`contact-${key}`}
                type={type}
                autoComplete="off"
                value={contact[key] ?? ""}
                onChange={optionalText(`contact.${key}`)}
                invalid={Boolean(errorFor(`contact.${key}`))}
              />
            </Field>
          ))}
        </div>
      </Card>

      <Card title="Work authorization & relocation">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field
            label="Visa sponsorship required"
            htmlFor="visa-required"
            needsInput={needs.has("work_authorization.visa_sponsorship_required")}
          >
            <TristateSelect
              id="visa-required"
              value={authorization.visa_sponsorship_required}
              onChange={(value) => update("work_authorization.visa_sponsorship_required", value)}
            />
          </Field>
          <Field label="Sponsorship needed" htmlFor="visa-when">
            <SelectInput
              id="visa-when"
              value={authorization.sponsorship_required_when ?? ""}
              onChange={(event) =>
                update(
                  "work_authorization.sponsorship_required_when",
                  event.target.value === "" ? null : event.target.value,
                )
              }
            >
              <option value="">Unknown</option>
              <option value="work_permit_needed">When a work permit is needed</option>
              <option value="always">Always</option>
              <option value="never">Never</option>
            </SelectInput>
          </Field>
          <Field
            label="Willing to relocate"
            htmlFor="relocate"
            needsInput={needs.has("relocation.willing_to_relocate")}
          >
            <TristateSelect
              id="relocate"
              value={profile.relocation.willing_to_relocate}
              onChange={(value) => update("relocation.willing_to_relocate", value)}
            />
          </Field>
        </div>
        <div className="mt-5">
          <p className={SMALL_LABEL}>Current work authorizations</p>
          <Rows
            items={authorization.current_work_authorizations}
            empty="None recorded."
            addLabel="Add authorization"
            onAdd={() =>
              update("work_authorization.current_work_authorizations", [
                ...authorization.current_work_authorizations,
                { country_code: "", status: "citizen" },
              ])
            }
            onRemove={(index) =>
              update(
                "work_authorization.current_work_authorizations",
                removeAt(authorization.current_work_authorizations, index),
              )
            }
            error={errorsUnder("work_authorization.current_work_authorizations")}
            render={(item, index) => (
              <>
                <TextInput
                  aria-label="Country code"
                  inline
                  className="w-20"
                  maxLength={2}
                  placeholder="TN"
                  value={item.country_code}
                  onChange={(event) =>
                    update(
                      `work_authorization.current_work_authorizations.${index}.country_code`,
                      event.target.value.toUpperCase(),
                    )
                  }
                />
                <SelectInput
                  aria-label="Status"
                  inline
                  className="w-52"
                  value={item.status}
                  onChange={(event) =>
                    update(
                      `work_authorization.current_work_authorizations.${index}.status`,
                      event.target.value as AuthorizationStatus,
                    )
                  }
                >
                  {AUTHORIZATION_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {humanize(value)}
                    </option>
                  ))}
                </SelectInput>
              </>
            )}
          />
        </div>
      </Card>

      <Card title="Targets">
        <div className="space-y-4">
          <Field
            label="Target roles"
            htmlFor="target-roles"
            needsInput={needs.has("targets.roles")}
            error={errorsUnder("targets.roles") ?? errorFor("targets.roles")}
          >
            <TagInput
              id="target-roles"
              tags={profile.targets.roles}
              onChange={(roles) => update("targets.roles", roles)}
            />
          </Field>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {(["primary", "secondary"] as const).map((tier) => (
              <div key={tier}>
                <p
                  className={`${SMALL_LABEL} ${tier === "primary" && needs.has("targets.countries.primary") ? "text-amber-700" : ""}`}
                >
                  {tier === "primary" ? "Primary countries" : "Secondary countries"}
                </p>
                <CountryRows
                  countries={profile.targets.countries[tier]}
                  onChange={(countries) => update(`targets.countries.${tier}`, countries)}
                  error={errorsUnder(`targets.countries.${tier}`)}
                />
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Core skills">
        <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
          Declared skills are not claims: a skill is used in a tailored CV only when the confirmed
          master CV provides evidence for it.{" "}
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-emerald-500" /> demonstrated
          </span>{" "}
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-sky-500" /> listed
          </span>{" "}
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-amber-500" /> no evidence
          </span>
        </p>
        <TagInput
          id="core-skills"
          tags={profile.core_skills}
          onChange={(values) => update("core_skills", values)}
          decorate={(tag) => {
            const strength = strengths.get(tag.toLowerCase());
            return (
              <span
                aria-hidden
                title={strength ? humanize(strength) : "Not evaluated yet (save first)"}
                className={`h-2 w-2 rounded-full ${strength ? STRENGTH_DOT[strength] : "bg-slate-300"}`}
              />
            );
          }}
        />
      </Card>

      <Card title="Application defaults">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field
            label="Notice period"
            htmlFor="notice-period"
            needsInput={needs.has("application_defaults.notice_period")}
            hint="For example: 1 month, immediately"
          >
            <TextInput
              id="notice-period"
              value={defaults.notice_period ?? ""}
              onChange={optionalText("application_defaults.notice_period")}
            />
          </Field>
          <Field
            label="Earliest start date"
            htmlFor="start-date"
            needsInput={needs.has("application_defaults.earliest_start_date")}
            error={errorFor("application_defaults.earliest_start_date")}
          >
            <TextInput
              id="start-date"
              type="date"
              value={defaults.earliest_start_date ?? ""}
              onChange={optionalText("application_defaults.earliest_start_date")}
            />
          </Field>
          <Field
            label="Preferred work modes"
            needsInput={needs.has("application_defaults.preferred_work_modes")}
          >
            <div className="flex flex-wrap gap-3 pt-1.5">
              {WORK_MODES.map((mode) => {
                const selected = defaults.preferred_work_modes ?? [];
                return (
                  <label key={mode} className="inline-flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.includes(mode)}
                      onChange={(event) => {
                        const next: WorkMode[] = event.target.checked
                          ? [...selected, mode]
                          : selected.filter((value) => value !== mode);
                        update(
                          "application_defaults.preferred_work_modes",
                          emptyToNull(WORK_MODES.filter((value) => next.includes(value))),
                        );
                      }}
                    />
                    {humanize(mode)}
                  </label>
                );
              })}
            </div>
          </Field>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div
            className={
              needs.has("application_defaults.languages")
                ? "rounded-lg p-2 ring-2 ring-amber-400/70"
                : ""
            }
            data-needs-input={needs.has("application_defaults.languages") ? "true" : undefined}
          >
            <p className={SMALL_LABEL}>Spoken languages</p>
            <Rows
              items={defaults.languages ?? []}
              empty="No languages recorded."
              addLabel="Add language"
              onAdd={() =>
                update("application_defaults.languages", [
                  ...(defaults.languages ?? []),
                  { language: "", level: "professional" },
                ])
              }
              onRemove={(index) =>
                update(
                  "application_defaults.languages",
                  emptyToNull(removeAt(defaults.languages ?? [], index)),
                )
              }
              error={errorsUnder("application_defaults.languages")}
              render={(item, index) => (
                <>
                  <TextInput
                    aria-label="Language"
                    inline
                    className="w-44"
                    placeholder="English"
                    value={item.language}
                    onChange={(event) =>
                      update(`application_defaults.languages.${index}.language`, event.target.value)
                    }
                  />
                  <SelectInput
                    aria-label="Level"
                    inline
                    className="w-40"
                    value={item.level}
                    onChange={(event) =>
                      update(
                        `application_defaults.languages.${index}.level`,
                        event.target.value as LanguageLevel,
                      )
                    }
                  >
                    {LANGUAGE_LEVELS.map((level) => (
                      <option key={level} value={level}>
                        {humanize(level)}
                      </option>
                    ))}
                  </SelectInput>
                </>
              )}
            />
          </div>

          <div
            className={
              needs.has("application_defaults.salary_expectations")
                ? "rounded-lg p-2 ring-2 ring-amber-400/70"
                : ""
            }
            data-needs-input={
              needs.has("application_defaults.salary_expectations") ? "true" : undefined
            }
          >
            <p className={SMALL_LABEL}>Salary expectations (gross)</p>
            <Rows
              items={defaults.salary_expectations ?? []}
              empty="No salary expectations recorded."
              addLabel="Add expectation"
              onAdd={() =>
                update("application_defaults.salary_expectations", [
                  ...(defaults.salary_expectations ?? []),
                  {
                    currency: "EUR",
                    minimum: 0,
                    maximum: null,
                    period: "year",
                    country_code: null,
                    note: null,
                  } satisfies SalaryExpectation,
                ])
              }
              onRemove={(index) =>
                update(
                  "application_defaults.salary_expectations",
                  emptyToNull(removeAt(defaults.salary_expectations ?? [], index)),
                )
              }
              error={errorsUnder("application_defaults.salary_expectations")}
              render={(item, index) => {
                const base = `application_defaults.salary_expectations.${index}`;
                return (
                  <>
                    <TextInput
                      aria-label="Minimum"
                      inline
                      type="number"
                      min={0}
                      className="w-28"
                      value={item.minimum}
                      onChange={(event) => update(`${base}.minimum`, Number(event.target.value))}
                    />
                    <TextInput
                      aria-label="Maximum"
                      inline
                      type="number"
                      min={0}
                      className="w-28"
                      placeholder="max"
                      value={item.maximum ?? ""}
                      onChange={(event) =>
                        update(
                          `${base}.maximum`,
                          event.target.value === "" ? null : Number(event.target.value),
                        )
                      }
                    />
                    <TextInput
                      aria-label="Currency"
                      inline
                      className="w-20"
                      maxLength={3}
                      value={item.currency}
                      onChange={(event) =>
                        update(`${base}.currency`, event.target.value.toUpperCase())
                      }
                    />
                    <SelectInput
                      aria-label="Period"
                      inline
                      className="w-28"
                      value={item.period}
                      onChange={(event) => update(`${base}.period`, event.target.value)}
                    >
                      <option value="year">per year</option>
                      <option value="month">per month</option>
                    </SelectInput>
                    <TextInput
                      aria-label="Country code (optional)"
                      inline
                      className="w-20"
                      maxLength={2}
                      placeholder="all"
                      value={item.country_code ?? ""}
                      onChange={(event) =>
                        update(
                          `${base}.country_code`,
                          event.target.value === "" ? null : event.target.value.toUpperCase(),
                        )
                      }
                    />
                  </>
                );
              }}
            />
          </div>
        </div>
      </Card>

      <Card title="CV policy">
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={profile.cv_policy.allow_title_changes}
            onChange={(event) => update("cv_policy.allow_title_changes", event.target.checked)}
          />
          <span>
            <span className="font-medium">Allow job title changes in tailored CVs</span>
            <span className="block text-slate-500 dark:text-slate-400">
              Off by default: titles stay exactly as in the master CV. Turn on only if you accept
              equivalent titles (for example &quot;ML Engineer&quot; for &quot;Machine Learning
              Engineer&quot;).
            </span>
          </span>
        </label>
      </Card>

      <div className="sticky bottom-0 z-10 -mx-6 border-t border-slate-200 bg-white/90 px-6 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        {notification && (
          <div className="mb-3">
            <Notice tone={notification.tone}>
              {notification.message}
              {notification.conflict && (
                <button
                  type="button"
                  className="ml-3 font-semibold underline"
                  onClick={() => window.location.reload()}
                >
                  Reload the latest version
                </button>
              )}
            </Notice>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={busy !== null || !dirty}>
            {busy === "save" ? "Saving…" : "Save profile"}
          </Button>
          <Button
            variant="secondary"
            disabled={busy !== null || !dirty}
            onClick={() => {
              setProfile(saved.profile);
              setErrors({});
              setNotification(null);
            }}
          >
            Discard changes
          </Button>
          <span className="text-xs text-slate-500">
            Version {saved.profile_version}
            {dirty ? " · unsaved changes" : ""}
          </span>
          <span className="ml-auto flex flex-wrap gap-2">
            <Button variant="secondary" disabled={busy !== null} onClick={() => void reimport()}>
              {busy === "import" ? "Importing…" : "Import from YAML"}
            </Button>
            {/* File downloads from the API proxy: a plain link, not client-side navigation. */}
            <a className={buttonClass("secondary")} href="/api/backend/candidate/export" download>
              Export YAML
            </a>
            <a
              className={buttonClass("ghost")}
              href="/api/backend/candidate/export?include_private=true"
              title="Includes contact details: keep the file out of Git"
              download
            >
              Export with private details
            </a>
          </span>
        </div>
      </div>
    </form>
  );
}

function TristateSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: boolean | null;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <SelectInput
      id={id}
      value={toTristate(value)}
      onChange={(event) => onChange(fromTristate(event.target.value))}
    >
      <option value="unknown">Unknown</option>
      <option value="yes">Yes</option>
      <option value="no">No</option>
    </SelectInput>
  );
}

function Rows<T>({
  items,
  render,
  onAdd,
  onRemove,
  addLabel,
  empty,
  error,
}: {
  items: readonly T[];
  render: (item: T, index: number) => ReactNode;
  onAdd: () => void;
  onRemove: (index: number) => void;
  addLabel: string;
  empty: string;
  error?: string;
}) {
  return (
    <div className="space-y-2">
      {items.length === 0 && <p className="text-sm text-slate-500">{empty}</p>}
      {items.map((item, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          {render(item, index)}
          <Button variant="ghost" small aria-label="Remove" onClick={() => onRemove(index)}>
            Remove
          </Button>
        </div>
      ))}
      {error && (
        <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
      <Button variant="secondary" small onClick={onAdd}>
        + {addLabel}
      </Button>
    </div>
  );
}

function CountryRows({
  countries,
  onChange,
  error,
}: {
  countries: readonly TargetCountry[];
  onChange: (countries: TargetCountry[]) => void;
  error?: string;
}) {
  return (
    <Rows
      items={countries}
      empty="No countries."
      addLabel="Add country"
      error={error}
      onAdd={() => onChange([...countries, { name: "", code: "" }])}
      onRemove={(index) => onChange(removeAt(countries, index))}
      render={(country, index) => (
        <>
          <input
            aria-label="Country"
            placeholder="France"
            value={country.name}
            onChange={(event) =>
              onChange(replaceAt(countries, index, { ...country, name: event.target.value }))
            }
            className={`${controlClass(false, true)} w-40`}
          />
          <input
            aria-label="Code"
            placeholder="FR"
            maxLength={2}
            value={country.code}
            onChange={(event) =>
              onChange(
                replaceAt(countries, index, { ...country, code: event.target.value.toUpperCase() }),
              )
            }
            className={`${controlClass(false, true)} w-16`}
          />
        </>
      )}
    />
  );
}
