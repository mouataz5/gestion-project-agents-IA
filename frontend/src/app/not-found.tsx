import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">404</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
        This page does not exist, or it belongs to a phase that is not implemented yet.
      </p>
      <Link
        href="/dashboard"
        className="mt-6 inline-block rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-500"
      >
        Back to the dashboard
      </Link>
    </div>
  );
}
