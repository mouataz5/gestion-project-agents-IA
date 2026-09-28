import { EmptyState, StatusBadge } from "@/components/ui";
import type { CandidateSkill } from "@/lib/api/types";
import { humanize } from "@/lib/format";

const STRENGTH_LABELS = {
  DEMONSTRATED: "Demonstrated",
  LISTED: "Listed only",
  NONE: "No evidence",
} as const;

/** Every declared or CV-listed skill with the master CV excerpts that support it. */
export function SkillEvidenceList({ skills }: { skills: readonly CandidateSkill[] }) {
  if (skills.length === 0) {
    return <EmptyState>No skills yet: declare core skills or confirm a master CV.</EmptyState>;
  }
  const counts = skills.reduce<Record<string, number>>((acc, skill) => {
    acc[skill.strength] = (acc[skill.strength] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <p className="mb-3 text-sm text-slate-500 dark:text-slate-400" data-testid="skill-counts">
        {counts.DEMONSTRATED ?? 0} demonstrated · {counts.LISTED ?? 0} listed only ·{" "}
        {counts.NONE ?? 0} without evidence (never used for tailoring)
      </p>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800" data-testid="skill-evidence">
        {skills.map((skill) => (
          <li key={skill.normalized_name} className="py-2" data-skill={skill.name}>
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                <span className="min-w-0">
                  <span className="font-medium break-words">{skill.name}</span>
                  {skill.category && (
                    <span className="ml-2 text-xs text-slate-500">{skill.category}</span>
                  )}
                </span>
                <span className="shrink-0">
                  <StatusBadge status={skill.strength} label={STRENGTH_LABELS[skill.strength]} />
                </span>
              </summary>
              <p className="mt-1 pl-3 text-xs text-slate-500">
                Source: {skill.sources.map(humanize).join(" + ")}
              </p>
              {skill.evidence.length > 0 ? (
                <ul className="mt-2 space-y-1 pl-3 text-sm">
                  {skill.evidence.map((item, index) => (
                    <li key={index} className="text-slate-600 dark:text-slate-300">
                      <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-600 uppercase dark:bg-slate-800 dark:text-slate-300">
                        {item.section}
                      </span>
                      {item.excerpt}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 pl-3 text-sm text-slate-500">
                  Not found in the confirmed master CV.
                </p>
              )}
            </details>
          </li>
        ))}
      </ul>
    </div>
  );
}
