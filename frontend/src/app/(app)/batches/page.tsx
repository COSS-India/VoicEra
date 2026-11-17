"use client";

import { Suspense } from "react";
import { Campaigns } from "@/components/dashboard/Campaigns";
import { useToast } from "@/components/ui/useToast";

export default function CampaignsPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Suspense fallback={null}>
        <Campaigns onNotify={notify} />
      </Suspense>
      {toastNode}
    </main>
  );
}
