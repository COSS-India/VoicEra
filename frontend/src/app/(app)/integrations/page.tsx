"use client";

import { Integrations } from "@/components/dashboard/Integrations";
import { useToast } from "@/components/ui/useToast";

export default function IntegrationsPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Integrations onNotify={notify} />
      {toastNode}
    </main>
  );
}
