import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

const CONTROL =
  "block rounded-lg border bg-white px-3 py-1.5 text-sm shadow-sm placeholder:text-slate-400 focus:ring-2 focus:outline-none disabled:opacity-60 dark:bg-slate-950";
const CONTROL_OK =
  "border-slate-300 focus:border-indigo-500 focus:ring-indigo-500/20 dark:border-slate-700";
const CONTROL_ERROR = "border-rose-400 focus:border-rose-500 focus:ring-rose-500/20";

/** Input styles. Full width by default; ``inline`` controls get their width from the caller. */
export function controlClass(invalid = false, inline = false): string {
  return `${CONTROL} ${inline ? "" : "w-full"} ${invalid ? CONTROL_ERROR : CONTROL_OK}`;
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  needsInput = false,
  children,
  className = "",
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string;
  needsInput?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`${className} ${needsInput ? "rounded-lg bg-amber-50/60 p-2 ring-2 ring-amber-400/70 dark:bg-amber-500/5" : ""}`}
      data-needs-input={needsInput ? "true" : undefined}
    >
      <label
        htmlFor={htmlFor}
        className="mb-1 flex flex-wrap items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200"
      >
        {label}
        {needsInput && (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
            Needs your input
          </span>
        )}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
      {error && (
        <p role="alert" className="mt-1 text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextInput({
  invalid,
  inline,
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; inline?: boolean }) {
  return (
    <input
      {...props}
      aria-invalid={invalid || undefined}
      className={`${controlClass(invalid, inline)} ${className}`}
    />
  );
}

export function TextArea({
  invalid,
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }) {
  return (
    <textarea
      {...props}
      aria-invalid={invalid || undefined}
      className={`${controlClass(invalid)} ${className}`}
    />
  );
}

export function SelectInput({
  invalid,
  inline,
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean; inline?: boolean }) {
  return (
    <select
      {...props}
      aria-invalid={invalid || undefined}
      className={`${controlClass(invalid, inline)} ${className}`}
    >
      {children}
    </select>
  );
}

const BUTTON_VARIANTS = {
  primary:
    "bg-indigo-600 text-white shadow-sm hover:bg-indigo-500 focus-visible:outline-indigo-600",
  secondary:
    "bg-white text-slate-700 ring-1 ring-slate-300 ring-inset hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-800",
  danger: "bg-rose-600 text-white shadow-sm hover:bg-rose-500 focus-visible:outline-rose-600",
  ghost:
    "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800",
} as const;

export function buttonClass(variant: keyof typeof BUTTON_VARIANTS = "primary", small = false) {
  return `inline-flex items-center justify-center gap-1.5 rounded-lg font-medium focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${small ? "px-2 py-1 text-xs" : "px-3.5 py-2 text-sm"} ${BUTTON_VARIANTS[variant]}`;
}

export function Button({
  variant = "primary",
  small = false,
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BUTTON_VARIANTS;
  small?: boolean;
}) {
  return (
    <button {...props} type={type} className={`${buttonClass(variant, small)} ${className}`} />
  );
}

export function Notice({
  tone,
  children,
}: {
  tone: "success" | "error" | "warning" | "info";
  children: ReactNode;
}) {
  const classes = {
    success:
      "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200",
    error:
      "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200",
    warning:
      "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200",
    info: "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200",
  }[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg border px-4 py-3 text-sm ${classes}`}
    >
      {children}
    </div>
  );
}
