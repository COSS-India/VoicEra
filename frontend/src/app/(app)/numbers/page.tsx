"use client";

import { PhoneNumbers } from "@/components/dashboard/PhoneNumbers";
import { useToast } from "@/components/ui/useToast";

export default function NumbersPage() {
  const { notify, toastNode } = useToast();

  return (
    <main className="flex w-full flex-col gap-6">
      <PhoneNumbers onNotify={notify} />
      {toastNode}
    </main>
  );
}
