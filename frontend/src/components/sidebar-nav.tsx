"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isActivePath, type NavItem } from "@/lib/nav";

export function SidebarNav({ items }: { items: Array<NavItem & { enabled: boolean }> }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {items.map((item) => {
        if (!item.enabled) {
          return (
            <span
              key={item.href}
              aria-disabled="true"
              title={`${item.description} — available in phase ${item.phase}`}
              className="flex cursor-not-allowed items-center justify-between rounded-md px-3 py-2 text-sm text-slate-400 dark:text-slate-600"
            >
              {item.label}
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-500">
                Phase {item.phase}
              </span>
            </span>
          );
        }
        const active = isActivePath(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-2 text-sm font-medium ${
              active
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
                : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
