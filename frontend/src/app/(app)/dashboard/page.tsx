"use client";

import { AgentsHome } from "@/components/dashboard/AgentsHome";
import { InitiativeFooter } from "@/components/dashboard/InitiativeFooter";
import { useToast } from "@/components/ui/useToast";

export default function DashboardPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex min-h-[calc(100vh-60px)] w-full flex-col gap-6">
      <AgentsHome onNotify={notify} />
      <InitiativeFooter />
      {toastNode}
    </main>
  );
}
