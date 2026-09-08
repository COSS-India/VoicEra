"use client";

import { Suspense } from "react";
import { History } from "@/components/dashboard/History";
import { useToast } from "@/components/ui/useToast";

export default function HistoryPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Suspense fallback={null}>
        <History onNotify={notify} />
      </Suspense>
      {toastNode}
    </main>
  );
}
