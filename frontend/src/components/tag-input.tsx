"use client";

import { type ReactNode, useState } from "react";

import { controlClass } from "@/components/form";
import { removeAt } from "@/lib/cv";
import { addTags } from "@/lib/profile";

/** Free-form tags: Enter or comma adds, × or Backspace (on an empty input) removes. */
export function TagInput({
  id,
  tags,
  onChange,
  placeholder = "Type and press Enter",
  decorate,
  invalid = false,
}: {
  id: string;
  tags: readonly string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  /** Optional marker rendered before a tag (e.g. skill evidence strength). */
  decorate?: (tag: string) => ReactNode;
  invalid?: boolean;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    if (draft.trim()) onChange(addTags(tags, draft));
    setDraft("");
  }

  return (
    <div className={`${controlClass(invalid)} flex flex-wrap items-center gap-1.5 px-1.5!`}>
      {tags.map((tag, index) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded-md bg-slate-100 py-0.5 pr-1 pl-2 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {decorate?.(tag)}
          {tag}
          <button
            type="button"
            aria-label={`Remove ${tag}`}
            onClick={() => onChange(removeAt(tags, index))}
            className="rounded px-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-700"
          >
            ×
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        placeholder={placeholder}
        onChange={(event) => {
          const value = event.target.value;
          if (value.includes(",")) {
            onChange(addTags(tags, value));
            setDraft("");
          } else {
            setDraft(value);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Backspace" && draft === "" && tags.length > 0) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={commit}
        className="min-w-40 flex-1 border-0 bg-transparent px-1.5 py-0.5 text-sm focus:ring-0 focus:outline-none"
      />
    </div>
  );
}
