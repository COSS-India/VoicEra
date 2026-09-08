"use client";

import { Members } from "@/components/dashboard/Members";
import { useToast } from "@/components/ui/useToast";

export default function MembersPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Members onNotify={notify} />
      {toastNode}
    </main>
  );
}
