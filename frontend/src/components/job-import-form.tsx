"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Dialog } from "@/components/dialog";
import { Button, Field, Notice, TextInput } from "@/components/form";
import type { ApiErrorResponse, JobImportRequest, JobImportResult } from "@/lib/api/types";
import { importErrorMessage } from "@/lib/jobs";
import { fieldErrors } from "@/lib/profile";

const EMPTY = { url: "", title: "", company: "", location: "", posted_text: "" };
type ImportForm = typeof EMPTY;

function requestBody(form: ImportForm): JobImportRequest {
  const optional = (value: string) => value.trim() || null;
  return {
    url: form.url.trim(),
    title: optional(form.title),
    company: optional(form.company),
    location: optional(form.location),
    posted_text: optional(form.posted_text),
  };
}

/**
 * Import a job the user found (the permitted path for LinkedIn): the URL is validated and
 * stored, never fetched. Details the user leaves empty stay empty.
 */
export function JobImportForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ImportForm>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  function update(name: keyof ImportForm, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      const response = await fetch("/api/backend/jobs/import", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(requestBody(form)),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setErrors(fieldErrors(body?.error?.details, ["body"]));
        setError(
          importErrorMessage(
            body?.error?.code,
            body?.error?.message ?? `Request failed (HTTP ${response.status})`,
          ),
        );
        return;
      }
      const result = (await response.json()) as JobImportResult;
      const outcome = result.created ? "created" : result.duplicate ? "duplicate" : "existing";
      setForm(EMPTY);
      setOpen(false);
      router.push(`/jobs/${result.job.id}?imported=${outcome}`);
      router.refresh();
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setOpen(false);
    setError(null);
    setErrors({});
  }

  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Import a job URL
      </Button>
      <Dialog
        open={open}
        onClose={close}
        title="Import a job URL"
        description="Paste a posting you found (LinkedIn, a career page, a job board). The page is not fetched: add the details you can see; anything left empty stays empty."
      >
        <form onSubmit={submit} aria-label="Import a job URL">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field
              label="Job URL"
              htmlFor="import-url"
              error={errors.url}
              className="md:col-span-2"
            >
              <TextInput
                id="import-url"
                type="url"
                required
                autoFocus
                placeholder="https://www.linkedin.com/jobs/view/…"
                value={form.url}
                invalid={Boolean(errors.url)}
                onChange={(event) => update("url", event.target.value)}
              />
            </Field>
            <Field label="Title" htmlFor="import-title" error={errors.title}>
              <TextInput
                id="import-title"
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
              />
            </Field>
            <Field label="Company" htmlFor="import-company" error={errors.company}>
              <TextInput
                id="import-company"
                value={form.company}
                onChange={(event) => update("company", event.target.value)}
              />
            </Field>
            <Field label="Location" htmlFor="import-location" error={errors.location}>
              <TextInput
                id="import-location"
                placeholder="Paris, France"
                value={form.location}
                onChange={(event) => update("location", event.target.value)}
              />
            </Field>
            <Field
              label="Posted"
              htmlFor="import-posted"
              hint="As shown on the page, e.g. “2 hours ago” or “il y a 3 jours”."
              error={errors.posted_text}
            >
              <TextInput
                id="import-posted"
                value={form.posted_text}
                onChange={(event) => update("posted_text", event.target.value)}
              />
            </Field>
          </div>
          {error && (
            <div className="mt-4">
              <Notice tone="error">{error}</Notice>
            </div>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="secondary" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !form.url.trim()}>
              {busy ? "Importing…" : "Import job"}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
