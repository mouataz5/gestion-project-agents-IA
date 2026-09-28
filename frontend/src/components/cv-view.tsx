import type { ReactNode } from "react";

import { Card, EmptyState } from "@/components/ui";
import type { ParsedCV } from "@/lib/api/types";
import { dateRangeLabel } from "@/lib/cv";

function Bullets({ items }: { items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-300">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}

function Entry({
  title,
  subtitle,
  dates,
  children,
}: {
  title: string;
  subtitle: string;
  dates: string;
  children: ReactNode;
}) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">
          {title}
          {subtitle && <span className="font-normal text-slate-500"> · {subtitle}</span>}
        </p>
        {dates && <p className="text-xs text-slate-500">{dates}</p>}
      </div>
      {children}
    </li>
  );
}

/** Read-only rendering of a confirmed (or superseded) master CV structure. */
export function CvStructureView({ structure }: { structure: ParsedCV }) {
  const categories = new Map<string, string[]>();
  for (const skill of structure.skills) {
    const key = skill.category ?? "Skills";
    categories.set(key, [...(categories.get(key) ?? []), skill.name]);
  }

  return (
    <div className="space-y-6" data-testid="cv-view">
      {structure.summary && (
        <Card title="Summary">
          <p className="text-sm whitespace-pre-line">{structure.summary}</p>
        </Card>
      )}
      <Card title={`Experience (${structure.experiences.length})`}>
        {structure.experiences.length === 0 ? (
          <EmptyState>No experience entries.</EmptyState>
        ) : (
          <ol className="divide-y divide-slate-100 dark:divide-slate-800">
            {structure.experiences.map((item, index) => (
              <Entry
                key={index}
                title={item.title}
                subtitle={[item.employer, item.location].filter(Boolean).join(", ")}
                dates={dateRangeLabel(item.dates)}
              >
                <Bullets items={[...item.details, ...item.bullets]} />
              </Entry>
            ))}
          </ol>
        )}
      </Card>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title={`Education (${structure.education.length})`}>
          <ol className="divide-y divide-slate-100 dark:divide-slate-800">
            {structure.education.map((item, index) => (
              <Entry
                key={index}
                title={item.degree}
                subtitle={[item.institution, item.location].filter(Boolean).join(", ")}
                dates={dateRangeLabel(item.dates)}
              >
                <Bullets items={[...item.details, ...item.bullets]} />
              </Entry>
            ))}
          </ol>
        </Card>
        <Card title={`Projects (${structure.projects.length})`}>
          <ol className="divide-y divide-slate-100 dark:divide-slate-800">
            {structure.projects.map((item, index) => (
              <Entry key={index} title={item.name} subtitle="" dates={dateRangeLabel(item.dates)}>
                <Bullets items={[...item.details, ...item.bullets]} />
              </Entry>
            ))}
          </ol>
        </Card>
        <Card title={`Skills (${structure.skills.length})`}>
          <dl className="space-y-2 text-sm">
            {[...categories.entries()].map(([category, names]) => (
              <div key={category}>
                <dt className="text-xs font-semibold text-slate-500 uppercase">{category}</dt>
                <dd>{names.join(", ")}</dd>
              </div>
            ))}
          </dl>
        </Card>
        <Card title="Certifications & languages">
          <Bullets items={structure.certifications} />
          {structure.languages.length > 0 && (
            <p className="mt-3 text-sm">
              <span className="text-slate-500">Languages: </span>
              {structure.languages.join(", ")}
            </p>
          )}
        </Card>
      </div>
      {structure.other_sections.map((section, index) => (
        <Card key={index} title={section.heading}>
          <Bullets items={section.lines} />
        </Card>
      ))}
    </div>
  );
}
