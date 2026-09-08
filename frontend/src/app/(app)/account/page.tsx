"use client";

import { Account } from "@/components/dashboard/Account";
import { useToast } from "@/components/ui/useToast";

export default function AccountPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <Account onNotify={notify} />
      {toastNode}
    </main>
  );
}
