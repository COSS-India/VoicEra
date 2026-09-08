"use client";

import { useState } from "react";
import { Toast } from "@/components/ui/Toast";

export function useToast() {
  const [toast, setToast] = useState<{ title: string; note: string } | null>(null);

  function notify(title: string, note: string) {
    setToast({ title, note });
    setTimeout(() => setToast(null), 4200);
  }

  const toastNode = toast ? (
    <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2">
      <Toast title={toast.title} note={toast.note} />
    </div>
  ) : null;

  return { notify, toastNode };
}
