"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";

const COLORS = ["#1F6FEB", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#0B0B0C"];

/** Lightweight framer-motion confetti burst — no extra dependency, just a handful of
 * pieces falling from the top with randomized drift/rotation/timing. */
export function Confetti({ count = 32 }: { count?: number }) {
  const pieces = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        id: i,
        left: Math.random() * 100,
        delay: Math.random() * 0.35,
        duration: 1.6 + Math.random() * 1.3,
        color: COLORS[i % COLORS.length],
        rotate: 180 + Math.random() * 360,
        drift: (Math.random() - 0.5) * 140,
        width: 5 + Math.random() * 5,
        height: 8 + Math.random() * 6,
      })),
    [count],
  );

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {pieces.map((p) => (
        <motion.span
          key={p.id}
          initial={{ y: -24, x: 0, opacity: 1, rotate: 0 }}
          animate={{ y: "110vh", x: p.drift, opacity: 0, rotate: p.rotate }}
          transition={{ duration: p.duration, delay: p.delay, ease: "easeIn" }}
          style={{
            position: "absolute",
            left: `${p.left}%`,
            top: 0,
            width: p.width,
            height: p.height,
            backgroundColor: p.color,
            borderRadius: 1.5,
          }}
        />
      ))}
    </div>
  );
}
