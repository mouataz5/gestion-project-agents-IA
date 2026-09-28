import type { ComponentHealth } from "@/lib/api/types";
import { humanize } from "@/lib/format";

import { StatusBadge } from "./ui";

export function HealthGrid({ components }: { components: ComponentHealth[] }) {
  return (
    <ul
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
      aria-label="Component health"
    >
      {components.map((component) => (
        <li
          key={component.name}
          data-testid={`health-${component.name}`}
          className="rounded-lg border border-slate-200 p-4 dark:border-slate-800"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{humanize(component.name)}</span>
            <StatusBadge status={component.status} />
          </div>
          <p
            className="mt-2 truncate text-xs text-slate-500 dark:text-slate-400"
            title={component.detail ?? undefined}
          >
            {component.detail ?? (component.critical ? "critical" : "optional")}
            {component.latency_ms != null && ` · ${Math.round(component.latency_ms)} ms`}
          </p>
        </li>
      ))}
    </ul>
  );
}
