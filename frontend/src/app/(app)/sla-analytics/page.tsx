"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SlaAnalytics } from "@/components/dashboard/SlaAnalytics";
import { useToast } from "@/components/ui/useToast";

function SlaAnalyticsPageInner() {
  const { notify, toastNode } = useToast();
  const searchParams = useSearchParams();
  const campaignId = searchParams.get("campaign");

  return (
    <>
      <SlaAnalytics onNotify={notify} initialCampaignId={campaignId} />
      {toastNode}
    </>
  );
}

export default function SlaAnalyticsPage() {
  return (
    <main className="flex w-full flex-col gap-6">
      <Suspense fallback={null}>
        <SlaAnalyticsPageInner />
      </Suspense>
    </main>
  );
}
