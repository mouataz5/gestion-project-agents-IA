"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { buttonClass } from "@/components/form";
import type { ApiErrorResponse, CvVersionDetail } from "@/lib/api/types";
import { checkCvFile, formatBytes, uploadErrorMessage } from "@/lib/cv";

const ACCEPT =
  ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/** Drag-and-drop upload of the master CV; opens the parsed draft for review. */
export function CvUpload({ maxBytes }: { maxBytes: number }) {
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    const problem = checkCvFile(file, maxBytes);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch("/api/backend/candidate/master-cv", {
        method: "POST",
        body: form,
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
        setError(
          uploadErrorMessage(
            body?.error?.code,
            body?.error?.message ?? `Upload failed (HTTP ${response.status})`,
          ),
        );
        return;
      }
      const version = (await response.json()) as CvVersionDetail;
      router.push(`/cv?version=${version.id}`);
      router.refresh();
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files[0];
        if (file) void upload(file);
      }}
      className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
        dragging
          ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10"
          : "border-slate-300 dark:border-slate-700"
      }`}
      data-testid="cv-dropzone"
    >
      <p className="text-sm font-medium">
        Drop your master CV here, or{" "}
        <label
          htmlFor="cv-file"
          className="cursor-pointer text-indigo-600 underline dark:text-indigo-400"
        >
          choose a file
        </label>
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        .docx or text-based .pdf · up to {formatBytes(maxBytes)} · 10 pages
      </p>
      <input
        id="cv-file"
        type="file"
        accept={ACCEPT}
        className="sr-only"
        disabled={busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void upload(file);
        }}
      />
      {busy && (
        <p role="status" className="mt-3 text-sm text-indigo-700 dark:text-indigo-300">
          Uploading and parsing…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
      <p className="mx-auto mt-4 max-w-xl text-xs text-slate-500 dark:text-slate-400">
        The file stays on this machine (never in Git). It is parsed without AI and nothing is
        invented: you review and correct the draft before confirming it as your master CV.
      </p>
      <label htmlFor="cv-file" className={`${buttonClass("secondary", true)} mt-3 cursor-pointer`}>
        Select file
      </label>
    </div>
  );
}
