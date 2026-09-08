"use client";

import { Campaigns } from "@/components/dashboard/Campaigns";
import { useToast } from "@/components/ui/useToast";

export default function CampaignsPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Campaigns onNotify={notify} />
      {toastNode}
    </main>
  );
}
