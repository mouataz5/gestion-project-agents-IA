export interface NavItem {
  href: string;
  label: string;
  /** Delivery phase that implements the page (see docs/implementation-plan.md). */
  phase: number;
  description: string;
}

export interface PhaseLike {
  number: number;
  status: string;
}

/** Pages from the specification (§19), in the specified order. */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard", phase: 1, description: "System overview" },
  { href: "/jobs", label: "Jobs", phase: 3, description: "Discovered jobs" },
  { href: "/applications", label: "Applications", phase: 9, description: "Review & approval" },
  { href: "/candidate", label: "Candidate", phase: 2, description: "Candidate profile" },
  { href: "/cv", label: "CV", phase: 2, description: "Master & tailored CVs" },
  { href: "/companies", label: "Companies", phase: 3, description: "Company watchlist" },
  { href: "/settings", label: "Settings", phase: 1, description: "Configuration" },
  { href: "/runs", label: "Runs", phase: 1, description: "Automation runs" },
];

export function implementedPhaseNumbers(phases: readonly PhaseLike[] | undefined): Set<number> {
  if (!phases) return new Set([1]);
  return new Set(phases.filter((phase) => phase.status === "done").map((phase) => phase.number));
}

export function navigationFor(
  implemented: ReadonlySet<number>,
): Array<NavItem & { enabled: boolean }> {
  return NAV_ITEMS.map((item) => ({ ...item, enabled: implemented.has(item.phase) }));
}

export function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
