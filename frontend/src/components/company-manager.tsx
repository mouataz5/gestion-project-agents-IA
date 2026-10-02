"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Dialog } from "@/components/dialog";
import { Button, Field, Notice, SelectInput, TextArea, TextInput } from "@/components/form";
import { TagInput } from "@/components/tag-input";
import { Badge, EmptyState } from "@/components/ui";
import {
  type ApiErrorResponse,
  COMPANY_ATS_TYPES,
  type CompanyImportResult,
  type CompanyRead,
} from "@/lib/api/types";
import {
  type CompanyForm,
  checkTone,
  companyCreateBody,
  companyToForm,
  companyUpdateBody,
  emptyCompanyForm,
} from "@/lib/companies";
import { formatDateTime, humanize } from "@/lib/format";
import { hostOf, jobsHref } from "@/lib/jobs";
import { fieldErrors } from "@/lib/profile";

type Message = { tone: "success" | "error"; text: string };

async function send(
  path: string,
  method: string,
  body?: unknown,
): Promise<
  | { ok: true; data: unknown }
  | { ok: false; error: ApiErrorResponse["error"] | null; status: number }
> {
  const response = await fetch(`/api/backend${path}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as ApiErrorResponse | null;
    return { ok: false, error: payload?.error ?? null, status: response.status };
  }
  return { ok: true, data: response.status === 204 ? null : await response.json() };
}

function CompanyFormDialog({
  company,
  open,
  onClose,
  onSaved,
}: {
  company: CompanyRead | null;
  open: boolean;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [form, setForm] = useState<CompanyForm>(() =>
    company ? companyToForm(company) : emptyCompanyForm(),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update<K extends keyof CompanyForm>(name: K, value: CompanyForm[K]) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrors({});
    setError(null);
    try {
      const result = company
        ? await send(`/companies/${company.id}`, "PATCH", companyUpdateBody(company, form))
        : await send("/companies", "POST", companyCreateBody(form));
      if (!result.ok) {
        setErrors(fieldErrors(result.error?.details, ["body"]));
        setError(result.error?.message ?? `Request failed (HTTP ${result.status})`);
        return;
      }
      onSaved(
        company ? `${form.name.trim()} updated.` : `${form.name.trim()} added to the watchlist.`,
      );
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={company ? `Edit ${company.name}` : "Add a company"}
      description="Watchlist companies are checked by every discovery run through their ATS board (real boards from Phase 10; in mock mode only the fictional boards exist)."
    >
      <form onSubmit={submit} aria-label="Company">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Name" htmlFor="company-name" error={errors.name}>
            <TextInput
              id="company-name"
              required
              value={form.name}
              invalid={Boolean(errors.name)}
              onChange={(event) => update("name", event.target.value)}
            />
          </Field>
          <Field label="Career page URL" htmlFor="company-url" error={errors.career_url}>
            <TextInput
              id="company-url"
              type="url"
              required
              placeholder="https://company.com/careers"
              value={form.career_url}
              invalid={Boolean(errors.career_url)}
              onChange={(event) => update("career_url", event.target.value)}
            />
          </Field>
          <Field
            label="Country code"
            htmlFor="company-country"
            hint="Two letters (ISO 3166), e.g. FR"
            error={errors.country_code}
          >
            <TextInput
              id="company-country"
              maxLength={2}
              value={form.country_code}
              invalid={Boolean(errors.country_code)}
              onChange={(event) => update("country_code", event.target.value.toUpperCase())}
            />
          </Field>
          <Field label="ATS" htmlFor="company-ats" error={errors.ats_type}>
            <SelectInput
              id="company-ats"
              value={form.ats_type}
              onChange={(event) =>
                update("ats_type", event.target.value as CompanyForm["ats_type"])
              }
            >
              {COMPANY_ATS_TYPES.map((type) => (
                <option key={type} value={type}>
                  {humanize(type)}
                </option>
              ))}
            </SelectInput>
          </Field>
          <Field
            label="Board token"
            htmlFor="company-token"
            hint="The company's identifier in its ATS (e.g. the Greenhouse board name)"
            error={errors.board_token}
          >
            <TextInput
              id="company-token"
              value={form.board_token}
              onChange={(event) => update("board_token", event.target.value)}
            />
          </Field>
          <Field label="Status" htmlFor="company-enabled">
            <label className="flex items-center gap-2 py-1.5 text-sm">
              <input
                id="company-enabled"
                type="checkbox"
                checked={form.enabled}
                onChange={(event) => update("enabled", event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-indigo-600"
              />
              Checked by discovery runs
            </label>
          </Field>
          <Field
            label="Target roles"
            htmlFor="company-roles"
            hint="Extra titles to keep for this company (besides your profile's target roles)"
            error={errors.target_roles}
            className="md:col-span-2"
          >
            <TagInput
              id="company-roles"
              tags={form.target_roles}
              onChange={(tags) => update("target_roles", tags)}
            />
          </Field>
          <Field
            label="Notes"
            htmlFor="company-notes"
            error={errors.notes}
            className="md:col-span-2"
          >
            <TextArea
              id="company-notes"
              rows={2}
              value={form.notes}
              onChange={(event) => update("notes", event.target.value)}
            />
          </Field>
        </div>
        {error && (
          <div className="mt-4">
            <Notice tone="error">{error}</Notice>
          </div>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : company ? "Save changes" : "Add company"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Watchlist table with add / edit / enable / remove and the companies.yaml import. */
export function CompanyManager({
  companies,
  timeZone,
}: {
  companies: CompanyRead[];
  timeZone: string;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState<{ company: CompanyRead | null; key: number } | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function run(key: string, action: () => Promise<Message | null>) {
    setBusy(key);
    setMessage(null);
    try {
      const result = await action();
      if (result) setMessage(result);
      router.refresh();
    } catch {
      setMessage({ tone: "error", text: "Could not reach the dashboard server." });
    } finally {
      setBusy(null);
    }
  }

  function importSeed() {
    void run("import", async () => {
      const result = await send("/companies/import", "POST");
      if (!result.ok) return { tone: "error", text: result.error?.message ?? "Import failed." };
      const counts = result.data as CompanyImportResult;
      return {
        tone: "success",
        text: `companies.yaml imported: ${counts.created} added, ${counts.updated} updated, ${counts.unchanged} unchanged.`,
      };
    });
  }

  function toggle(company: CompanyRead) {
    void run(company.id, async () => {
      const result = await send(`/companies/${company.id}`, "PATCH", { enabled: !company.enabled });
      return result.ok ? null : { tone: "error", text: result.error?.message ?? "Update failed." };
    });
  }

  function remove(company: CompanyRead) {
    if (!window.confirm(`Remove ${company.name} from the watchlist? Its jobs are kept.`)) return;
    void run(company.id, async () => {
      const result = await send(`/companies/${company.id}`, "DELETE");
      return result.ok
        ? { tone: "success", text: `${company.name} removed from the watchlist.` }
        : { tone: "error", text: result.error?.message ?? "Delete failed." };
    });
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {companies.length} compan{companies.length === 1 ? "y" : "ies"} ·{" "}
          {companies.filter((company) => company.enabled).length} checked by discovery runs
        </p>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={importSeed} disabled={busy === "import"}>
            {busy === "import" ? "Importing…" : "Import companies.yaml"}
          </Button>
          <Button onClick={() => setEditing({ company: null, key: Date.now() })}>
            Add company
          </Button>
        </div>
      </div>

      {message && (
        <div className="mb-4">
          <Notice tone={message.tone}>{message.text}</Notice>
        </div>
      )}

      {companies.length === 0 ? (
        <EmptyState>
          The watchlist is empty. Add the companies you want to follow, or import the example seed
          from <code className="font-mono">crawler/companies.yaml</code>.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
              <tr className="border-b border-slate-200 dark:border-slate-800">
                <th className="py-2 pr-4 font-medium">Company</th>
                <th className="py-2 pr-4 font-medium">ATS</th>
                <th className="py-2 pr-4 font-medium">Target roles</th>
                <th className="py-2 pr-4 text-right font-medium">Jobs</th>
                <th className="py-2 pr-4 font-medium">Last check</th>
                <th className="py-2 pr-4 font-medium">Enabled</th>
                <th className="py-2 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => (
                <tr
                  key={company.id}
                  data-testid="company-row"
                  className="border-b border-slate-100 align-top last:border-0 dark:border-slate-800/60"
                >
                  <td className="py-2.5 pr-4">
                    <div className="font-medium">{company.name}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {company.country ?? company.country_code ?? "Country not set"} ·{" "}
                      <a
                        href={company.career_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="whitespace-nowrap hover:underline"
                      >
                        {hostOf(company.career_url)} ↗
                      </a>
                    </div>
                  </td>
                  <td className="py-2.5 pr-4">
                    <div>{humanize(company.ats_type)}</div>
                    {company.board_token && (
                      <div className="font-mono text-xs text-slate-400">{company.board_token}</div>
                    )}
                  </td>
                  <td className="py-2.5 pr-4">
                    <div className="flex max-w-xs flex-wrap gap-1">
                      {company.target_roles.length === 0 ? (
                        <span className="text-xs text-slate-400">Profile roles only</span>
                      ) : (
                        company.target_roles.map((role) => (
                          <span
                            key={role}
                            className="rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800"
                          >
                            {role}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 pr-4 text-right tabular-nums">
                    {company.job_count > 0 ? (
                      <Link
                        href={jobsHref({ tab: "all", q: company.name })}
                        className="text-indigo-600 hover:underline dark:text-indigo-400"
                      >
                        {company.job_count}
                      </Link>
                    ) : (
                      0
                    )}
                  </td>
                  <td className="py-2.5 pr-4">
                    {company.last_check_status ? (
                      <div className="flex flex-col gap-1">
                        <Badge tone={checkTone(company.last_check_status)}>
                          {company.last_check_status}
                        </Badge>
                        <span className="text-xs whitespace-nowrap text-slate-500 dark:text-slate-400">
                          {formatDateTime(company.last_checked_at, timeZone)}
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400">Never checked</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-4">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={company.enabled}
                      aria-label={`Check ${company.name} in discovery runs`}
                      disabled={busy === company.id}
                      onClick={() => toggle(company)}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
                        company.enabled ? "bg-indigo-600" : "bg-slate-300 dark:bg-slate-700"
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                          company.enabled ? "translate-x-4" : "translate-x-0.5"
                        }`}
                      />
                    </button>
                  </td>
                  <td className="py-2.5 text-right whitespace-nowrap">
                    <Button
                      variant="ghost"
                      small
                      onClick={() => setEditing({ company, key: Date.now() })}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      small
                      disabled={busy === company.id}
                      onClick={() => remove(company)}
                      className="text-rose-600! dark:text-rose-400!"
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <CompanyFormDialog
          key={editing.key}
          company={editing.company}
          open
          onClose={() => setEditing(null)}
          onSaved={(text) => {
            setEditing(null);
            setMessage({ tone: "success", text });
            router.refresh();
          }}
        />
      )}
    </>
  );
}
