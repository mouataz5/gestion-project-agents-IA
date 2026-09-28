import type { Metadata } from "next";
import Link from "next/link";

import { SidebarNav } from "@/components/sidebar-nav";
import { Badge } from "@/components/ui";
import type { SystemInfo } from "@/lib/api/types";
import { implementedPhaseNumbers, navigationFor } from "@/lib/nav";
import { backendGet } from "@/lib/server/backend";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Job Agent", template: "%s · Job Agent" },
  description: "Self-hosted AI job application agent",
};

function SafetyBanner({ info }: { info: SystemInfo | null }) {
  if (!info) {
    return (
      <Badge tone="danger">
        <span data-testid="backend-status">Backend unreachable</span>
      </Badge>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="safety-badges">
      {info.mock_mode ? (
        <Badge tone="warning">
          <span data-testid="mock-mode-badge">MOCK MODE · no real submissions</span>
        </Badge>
      ) : (
        <Badge tone="danger">LIVE MODE</Badge>
      )}
      <Badge tone={info.auto_submit ? "danger" : "success"}>
        Auto-submit {info.auto_submit ? "ON" : "OFF"}
      </Badge>
      {!info.auth_enabled && <Badge tone="danger">API auth disabled</Badge>}
      <span className="text-xs text-slate-500 dark:text-slate-400">
        {info.environment} · v{info.version}
      </span>
    </div>
  );
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const result = await backendGet<SystemInfo>("/system/info");
  const info = result.ok ? result.data : null;
  const navigation = navigationFor(implementedPhaseNumbers(info?.phases));

  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <div className="flex min-h-screen">
          <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-6 border-r border-slate-200 bg-white p-4 md:flex dark:border-slate-800 dark:bg-slate-900">
            <Link href="/dashboard" className="px-3 pt-2">
              <span className="block text-base font-semibold tracking-tight">Job Agent</span>
              <span className="block text-xs text-slate-500 dark:text-slate-400">
                AI job application platform
              </span>
            </Link>
            <SidebarNav items={navigation} />
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-6 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
              <Link href="/dashboard" className="font-semibold md:hidden">
                Job Agent
              </Link>
              <SafetyBanner info={info} />
            </header>
            <main className="mx-auto w-full max-w-6xl flex-1 p-6">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
