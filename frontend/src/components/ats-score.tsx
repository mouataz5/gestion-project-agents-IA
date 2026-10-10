import Link from "next/link";

import { scoreTone } from "@/lib/ats";

import { Badge } from "./ui";

/** An ATS score, coloured against the target (and the reachable ceiling when known). */
export function AtsScoreBadge({
  score,
  target,
  ceiling,
  href,
  size,
}: {
  score: number;
  target: number;
  ceiling?: number | null;
  href?: string;
  size?: "sm" | "lg";
}) {
  const badge = (
    <span data-testid="ats-score" title={`ATS score ${score.toFixed(1)} (target ${target})`}>
      <Badge tone={scoreTone(score, target, ceiling)} size={size}>
        ATS {score.toFixed(1)}
      </Badge>
    </span>
  );
  return href ? (
    <Link href={href} className="hover:opacity-80">
      {badge}
    </Link>
  ) : (
    badge
  );
}
