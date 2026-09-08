"use client";

import { AgentsHome } from "@/components/dashboard/AgentsHome";
import { useToast } from "@/components/ui/useToast";

export default function DashboardPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <AgentsHome onNotify={notify} />
      {toastNode}
    </main>
  );
}
