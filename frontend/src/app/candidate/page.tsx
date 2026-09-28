import type { Metadata } from "next";
import Link from "next/link";

import { CandidateProfileForm } from "@/components/candidate-form";
import { SkillEvidenceList } from "@/components/skill-evidence";
import { BackendError, Card, PageHeader, StatusBadge } from "@/components/ui";
import type { CandidateRead, CandidateSkill } from "@/lib/api/types";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Candidate" };

export default async function CandidatePage() {
  const [candidateResult, skillsResult] = await Promise.all([
    backendGet<CandidateRead>("/candidate"),
    backendGet<CandidateSkill[]>("/candidate/skills"),
  ]);
  if (!candidateResult.ok) {
    return (
      <>
        <PageHeader title="Candidate profile" />
        <BackendError message={candidateResult.message} />
      </>
    );
  }
  const candidate = candidateResult.data;
  const skills = skillsResult.ok ? skillsResult.data : [];
  const master = candidate.active_master_cv;

  return (
    <>
      <PageHeader
        title="Candidate profile"
        description="Identity, constraints and preferences. Experience and skills come only from the confirmed master CV."
        action={
          master ? (
            <Link href={`/cv?version=${master.id}`} className="text-sm">
              <StatusBadge status="CONFIRMED" label={`Master CV v${master.version}`} />
            </Link>
          ) : (
            <Link
              href="/cv"
              className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              No confirmed master CV yet: upload one →
            </Link>
          )
        }
      />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <CandidateProfileForm initial={candidate} skills={skills} />
        <div className="xl:sticky xl:top-6 xl:self-start">
          <Card title="Skill evidence">
            <SkillEvidenceList skills={skills} />
          </Card>
        </div>
      </div>
    </>
  );
}
