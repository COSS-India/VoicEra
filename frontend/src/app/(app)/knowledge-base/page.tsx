"use client";

import { KnowledgeBase } from "@/components/dashboard/KnowledgeBase";
import { useToast } from "@/components/ui/useToast";

export default function KnowledgeBasePage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <KnowledgeBase onNotify={notify} />
      {toastNode}
    </main>
  );
}
