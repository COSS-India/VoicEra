"use client";

import { Analytics } from "@/components/dashboard/Analytics";
import { useToast } from "@/components/ui/useToast";

export default function AnalyticsPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Analytics onNotify={notify} />
      {toastNode}
    </main>
  );
}
