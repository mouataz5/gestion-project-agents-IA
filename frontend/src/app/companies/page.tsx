import type { Metadata } from "next";

import { CompanyManager } from "@/components/company-manager";
import { BackendError, Card, PageHeader } from "@/components/ui";
import type { CompanyRead, SystemInfo } from "@/lib/api/types";
import { backendGet } from "@/lib/server/backend";

export const metadata: Metadata = { title: "Companies" };

export default async function CompaniesPage() {
  const [companiesResult, infoResult] = await Promise.all([
    backendGet<CompanyRead[]>("/companies"),
    backendGet<SystemInfo>("/system/info"),
  ]);
  const timeZone = infoResult.ok ? infoResult.data.config.timezone : "UTC";

  return (
    <>
      <PageHeader
        title="Company watchlist"
        description="Companies whose job boards are checked by every discovery run. Jobs are kept when a company is removed."
      />
      <Card>
        {companiesResult.ok ? (
          <CompanyManager companies={companiesResult.data} timeZone={timeZone} />
        ) : (
          <BackendError message={companiesResult.message} />
        )}
      </Card>
    </>
  );
}
