"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Confetti } from "@/components/ui/Confetti";
import { VoicEraMark } from "@/components/ui/VoicEraMark";

interface SuccessScreenProps {
  eyebrow: string;
  title: string;
  description: string;
  actionLabel: string;
  onAction: () => void;
  /** Auto-triggers `onAction` after this many ms; pass 0 to disable. */
  autoRedirectMs?: number;
}

/** Reusable success moment: confetti burst, the VoicEra mark, a spring-in
 * checkmark, and an action that also fires automatically after a short delay. */
export function SuccessScreen({
  eyebrow,
  title,
  description,
  actionLabel,
  onAction,
  autoRedirectMs = 4000,
}: SuccessScreenProps) {
  useEffect(() => {
    if (!autoRedirectMs) return;
    const timer = window.setTimeout(onAction, autoRedirectMs);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRedirectMs]);

  return (
    <main className="relative flex min-h-screen w-full items-center justify-center overflow-hidden px-8 text-center">
      <Confetti />
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 22 }}
        className="flex max-w-lg flex-col items-center gap-4"
      >
        <motion.span
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.05 }}
          className="text-v-fg"
        >
          <VoicEraMark size={30} />
        </motion.span>

        <motion.span
          initial={{ scale: 0, rotate: -20 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 16, delay: 0.15 }}
          className="flex size-14 items-center justify-center rounded-full bg-v-accent text-white"
        >
          <CheckCircle2 className="size-7" strokeWidth={1.75} />
        </motion.span>

        <span className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">{eyebrow}</span>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm font-light text-v-muted-2">{description}</p>
        <Button onClick={onAction}>{actionLabel}</Button>
      </motion.div>
    </main>
  );
}
