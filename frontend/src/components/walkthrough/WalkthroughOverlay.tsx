"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { AgentWaveIcon } from "@/components/ui/VoicEraMark";
import type {
  WalkthroughArrowFrom,
  WalkthroughCardPlacement,
  WalkthroughStep,
  WalkthroughTargetAnchor,
} from "./types";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
  right: number;
  bottom: number;
}

function toRect(r: DOMRect): Rect {
  return {
    top: r.top,
    left: r.left,
    width: r.width,
    height: r.height,
    right: r.right,
    bottom: r.bottom,
  };
}

interface Point {
  x: number;
  y: number;
}

const EASE_OUT = [0.22, 1, 0.36, 1] as const;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function cardArrowOrigin(card: Rect, anchor: WalkthroughArrowFrom): Point {
  switch (anchor) {
    case "logo":
      return { x: card.left + 26, y: card.top + 26 };
    case "left":
      return { x: card.left, y: card.top + card.height * 0.42 };
    case "top":
      return { x: card.left + card.width * 0.34, y: card.top };
    case "bottom-left":
      return { x: card.left + 18, y: card.top + card.height - 14 };
    default:
      return { x: card.left + card.width / 2, y: card.top + card.height / 2 };
  }
}

function targetArrowPoint(spotlight: Rect, anchor: WalkthroughTargetAnchor): Point {
  switch (anchor) {
    case "left-edge":
      return {
        x: spotlight.right - 4,
        y: spotlight.top + spotlight.height * 0.46,
      };
    case "top-center":
      return {
        x: spotlight.left + spotlight.width * 0.55,
        y: spotlight.top + 6,
      };
    case "bottom-center":
      return {
        x: spotlight.left + spotlight.width / 2,
        y: spotlight.bottom + 14,
      };
    case "center":
    default:
      return {
        x: spotlight.left + spotlight.width / 2,
        y: spotlight.top + spotlight.height / 2,
      };
  }
}

function curvedPath(from: Point, to: Point, bow = 0.2) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.hypot(dx, dy) || 1;
  const nx = -dy / dist;
  const ny = dx / dist;
  const offset = dist * bow;

  const c1 = {
    x: from.x + dx * 0.32 + nx * offset * 1.15,
    y: from.y + dy * 0.32 + ny * offset * 1.15,
  };
  const c2 = {
    x: to.x - dx * 0.22 + nx * offset * 0.9,
    y: to.y - dy * 0.22 + ny * offset * 0.9,
  };

  return `M ${from.x} ${from.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${to.x} ${to.y}`;
}

/** Sample evenly spaced points along an SVG path for dot rendering. */
function samplePathDots(pathD: string, spacing: number): Point[] {
  if (typeof document === "undefined") return [];
  const el = document.createElementNS("http://www.w3.org/2000/svg", "path");
  el.setAttribute("d", pathD);
  const length = el.getTotalLength();
  if (!length) return [];

  const pts: Point[] = [];
  for (let dist = spacing; dist < length - spacing * 0.6; dist += spacing) {
    const p = el.getPointAtLength(dist);
    pts.push({ x: p.x, y: p.y });
  }
  return pts;
}

const DOT_RADIUS = 2.8;
const DOT_SPACING = 14;

function computeCardPosition(
  target: Rect,
  cardW: number,
  cardH: number,
  placement: WalkthroughCardPlacement = "right-of-target",
): { top: number; left: number } {
  const margin = 36;
  const pad = 16;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let top: number;
  let left: number;

  switch (placement) {
    case "right-of-target":
      left = target.right + margin;
      top = target.top + target.height * 0.34 - cardH * 0.25;
      break;
    case "below-target":
      left = target.left + target.width * 0.08;
      top = target.bottom + margin;
      break;
    case "bottom-right":
      left = vw - cardW - pad - 48;
      top = vh * 0.52 - cardH * 0.15;
      break;
    case "above-target":
      left = target.right + 72;
      top = vh * 0.44 - cardH / 2;
      break;
    default:
      left = target.right + margin;
      top = target.top + target.height / 2 - cardH / 2;
  }

  return {
    left: clamp(left, pad, vw - cardW - pad),
    top: clamp(top, pad, vh - cardH - pad),
  };
}

function TourArrow({
  from,
  to,
  bow,
  stepKey,
  reduceMotion,
}: {
  from: Point;
  to: Point;
  bow: number;
  stepKey: string;
  reduceMotion: boolean | null;
}) {
  const path = curvedPath(from, to, bow);
  const dots = useMemo(() => samplePathDots(path, DOT_SPACING), [path]);
  const spring = reduceMotion
    ? { duration: 0.01 }
    : { type: "spring" as const, stiffness: 280, damping: 30 };

  return (
    <svg
      className="pointer-events-none fixed inset-0 z-[97]"
      aria-hidden
      width="100%"
      height="100%"
    >
      {dots.map((dot, index) => (
        <motion.circle
          key={`${stepKey}-dot-${index}`}
          cx={dot.x}
          cy={dot.y}
          r={DOT_RADIUS}
          fill="var(--v-accent)"
          initial={reduceMotion ? false : { opacity: 0, scale: 0 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={
            reduceMotion
              ? { duration: 0.01 }
              : {
                  opacity: { duration: 0.22, ease: EASE_OUT, delay: 0.1 + index * 0.03 },
                  scale: {
                    type: "spring",
                    stiffness: 480,
                    damping: 26,
                    delay: 0.1 + index * 0.03,
                  },
                }
          }
        />
      ))}
      {/* Origin pin */}
      <motion.g
        initial={false}
        animate={{ x: from.x, y: from.y }}
        transition={spring}
      >
        <motion.circle
          cx={0}
          cy={0}
          r="5.5"
          fill="var(--v-accent)"
          initial={reduceMotion ? false : { scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{
            scale: reduceMotion
              ? { duration: 0.01 }
              : { type: "spring", stiffness: 420, damping: 24, delay: 0.18 },
            opacity: { duration: 0.2, delay: 0.15 },
          }}
        />
        <motion.circle
          cx={0}
          cy={0}
          r="2"
          fill="white"
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2, delay: 0.22 }}
        />
      </motion.g>

      {/* Target pin */}
      <motion.g
        initial={false}
        animate={{ x: to.x, y: to.y }}
        transition={spring}
      >
        <motion.circle
          cx={0}
          cy={0}
          r="8"
          fill="var(--v-fg)"
          initial={reduceMotion ? false : { scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{
            scale: reduceMotion
              ? { duration: 0.01 }
              : { type: "spring", stiffness: 420, damping: 24, delay: 0.42 },
            opacity: { duration: 0.2, delay: 0.38 },
          }}
        />
        <motion.circle
          cx={0}
          cy={0}
          r="3"
          fill="white"
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2, delay: 0.46 }}
        />
      </motion.g>
    </svg>
  );
}

const contentVariants = {
  enter: (direction: number) => ({
    opacity: 0,
    x: direction > 0 ? 14 : -14,
    filter: "blur(2px)",
  }),
  center: {
    opacity: 1,
    x: 0,
    filter: "blur(0px)",
  },
  exit: (direction: number) => ({
    opacity: 0,
    x: direction > 0 ? -10 : 10,
    filter: "blur(2px)",
  }),
};

export function WalkthroughOverlay({
  step,
  stepNumber,
  totalSteps,
  onAdvance,
  onBack,
  onSkip,
}: {
  step: WalkthroughStep;
  stepNumber: number;
  totalSteps: number;
  onAdvance: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  const targetId = step.target;
  const isIntro = step.presentation === "intro" || !targetId;
  const reduceMotion = useReducedMotion();

  const cardRef = useRef<HTMLDivElement>(null);
  const prevStepRef = useRef(stepNumber);
  const direction = stepNumber >= prevStepRef.current ? 1 : -1;

  const [targetRect, setTargetRect] = useState<Rect | null>(null);
  const [cardRect, setCardRect] = useState<Rect | null>(null);
  const [cardPos, setCardPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    prevStepRef.current = stepNumber;
  }, [stepNumber]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    if (isIntro) {
      setTargetRect(null);
      setCardRect(null);
      return;
    }

    function measure() {
      const el = document.querySelector(`[data-tour="${targetId}"]`);
      if (!el) {
        setTargetRect(null);
        return;
      }
      setTargetRect(toRect(el.getBoundingClientRect()));
    }

    measure();
    const id = window.setInterval(measure, 400);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [isIntro, targetId]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;

    function measureCard() {
      const el = cardRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();

      if (isIntro) {
        const top = window.innerHeight / 2 - r.height / 2;
        const left = window.innerWidth / 2 - r.width / 2;
        const rect = toRect(r);
        rect.top = top;
        rect.left = left;
        rect.right = left + r.width;
        rect.bottom = top + r.height;
        setCardPos({ top, left });
        setCardRect(rect);
        return;
      }

      if (!targetRect) return;

      const pad = 6;
      const spotlight: Rect = {
        top: targetRect.top - pad,
        left: targetRect.left - pad,
        width: targetRect.width + pad * 2,
        height: targetRect.height + pad * 2,
        right: targetRect.right + pad,
        bottom: targetRect.bottom + pad,
      };

      const pos = computeCardPosition(
        spotlight,
        r.width,
        r.height,
        step.cardPlacement ?? "right-of-target",
      );
      const rect = toRect(r);
      rect.top = pos.top;
      rect.left = pos.left;
      rect.right = pos.left + r.width;
      rect.bottom = pos.top + r.height;
      setCardPos(pos);
      setCardRect(rect);
    }

    measureCard();
    window.addEventListener("resize", measureCard);
    return () => window.removeEventListener("resize", measureCard);
  }, [isIntro, targetRect, stepNumber, step.cardPlacement]);

  const fade = reduceMotion ? { duration: 0.01 } : { duration: 0.38, ease: EASE_OUT };
  const spring = reduceMotion
    ? { duration: 0.01 }
    : { type: "spring" as const, stiffness: 260, damping: 32, mass: 0.9 };
  const contentTransition = reduceMotion
    ? { duration: 0.01 }
    : { duration: 0.32, ease: EASE_OUT };

  const pad = 6;
  const spotlight = targetRect
    ? {
        top: targetRect.top - pad,
        left: targetRect.left - pad,
        width: targetRect.width + pad * 2,
        height: targetRect.height + pad * 2,
        right: targetRect.right + pad,
        bottom: targetRect.bottom + pad,
      }
    : null;

  const arrow =
    cardRect && spotlight
      ? {
          from: cardArrowOrigin(cardRect, step.arrowFrom ?? "left"),
          to: targetArrowPoint(spotlight, step.targetAnchor ?? "center"),
          bow: step.arrowBow ?? 0.2,
        }
      : null;

  const skipLabel = stepNumber === 1 ? "Skip the tour" : "Skip the rest";
  const advanceLabel =
    stepNumber === 1 ? "Show me" : stepNumber === totalSteps ? "Finish" : "Next";

  const cardReady = isIntro ? true : Boolean(cardPos && targetRect);

  return (
    <motion.div
      className="pointer-events-none fixed inset-0 z-[95]"
      aria-live="polite"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={fade}
    >
      <AnimatePresence mode="sync">
        {isIntro ? (
          <motion.div
            key="intro-backdrop"
            className="absolute inset-0 bg-[rgba(15,17,21,0.62)]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={fade}
          />
        ) : spotlight ? (
          <motion.div
            key="spotlight-backdrop"
            className="absolute rounded-v-lg ring-2 ring-white"
            initial={
              reduceMotion
                ? false
                : {
                    opacity: 0,
                    scale: 0.98,
                    top: spotlight.top,
                    left: spotlight.left,
                    width: spotlight.width,
                    height: spotlight.height,
                  }
            }
            animate={{
              opacity: 1,
              scale: 1,
              top: spotlight.top,
              left: spotlight.left,
              width: spotlight.width,
              height: spotlight.height,
            }}
            exit={{ opacity: 0, transition: { duration: 0.22, ease: EASE_OUT } }}
            transition={{
              opacity: { ...fade, delay: reduceMotion ? 0 : 0.06 },
              scale: spring,
              top: spring,
              left: spring,
              width: spring,
              height: spring,
            }}
            style={{ boxShadow: "0 0 0 9999px rgba(15, 17, 21, 0.62)" }}
          />
        ) : (
          <motion.div
            key="loading-backdrop"
            className="absolute inset-0 bg-[rgba(15,17,21,0.62)]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.45 }}
            exit={{ opacity: 0 }}
            transition={fade}
          />
        )}
      </AnimatePresence>

      <div
        className={
          isIntro
            ? "pointer-events-none fixed inset-0 z-[96] flex items-center justify-center px-4"
            : "pointer-events-none fixed inset-0 z-[96]"
        }
      >
        <motion.div
          key={step.id}
          ref={cardRef}
          className={`pointer-events-auto w-[min(420px,calc(100vw-32px))] rounded-v-xl border border-v-line bg-white p-6 shadow-[0_24px_60px_rgba(11,11,12,0.18)] ${
            isIntro ? "relative" : "absolute"
          }`}
          initial={
            reduceMotion
              ? false
              : isIntro
                ? { opacity: 0, y: 18, scale: 0.97 }
                : {
                    opacity: 0,
                    y: 18,
                    scale: 0.97,
                    top: cardPos?.top ?? 0,
                    left: cardPos?.left ?? 0,
                  }
          }
          animate={
            isIntro
              ? { opacity: 1, y: 0, scale: 1 }
              : {
                  opacity: cardReady ? 1 : 0,
                  y: 0,
                  scale: 1,
                  top: cardPos?.top ?? 0,
                  left: cardPos?.left ?? 0,
                }
          }
          transition={{
            opacity: { ...fade, delay: reduceMotion ? 0 : 0.1 },
            y: { ...spring, delay: reduceMotion ? 0 : 0.1 },
            scale: { ...spring, delay: reduceMotion ? 0 : 0.1 },
            top: spring,
            left: spring,
          }}
          style={
            !isIntro && !cardPos ? { visibility: "hidden", top: 0, left: 0 } : undefined
          }
        >
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={step.id}
            custom={direction}
            variants={reduceMotion ? undefined : contentVariants}
            initial={reduceMotion ? false : "enter"}
            animate="center"
            exit={reduceMotion ? undefined : "exit"}
            transition={contentTransition}
          >
            <div className="flex gap-4">
              <motion.div
                className="relative flex size-[52px] shrink-0 items-center justify-center"
                initial={reduceMotion ? false : { scale: 0.85, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ ...spring, delay: reduceMotion ? 0 : 0.05 }}
              >
                <span className="absolute inset-0 rounded-full border border-v-accent/15" />
                <span className="absolute inset-[5px] rounded-full border border-v-accent/25" />
                <span className="absolute inset-[10px] rounded-full border border-v-accent/35" />
                <AgentWaveIcon className="relative z-[1] !h-10 !w-10" />
              </motion.div>
              <div className="min-w-0 flex-1">
                <span className="font-mono text-[10px] font-semibold uppercase tracking-[.16em] text-v-dim">
                  Step {stepNumber} of {totalSteps}
                </span>
                <h3 className="mt-1.5 text-[19px] font-extrabold leading-snug tracking-[-.35px] text-v-fg">
                  {step.title}
                </h3>
                <p className="mt-2 text-[13.5px] font-light leading-relaxed text-v-muted">{step.body}</p>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>

        <div className="mt-5 flex items-center gap-1.5">
          {Array.from({ length: totalSteps }).map((_, index) => (
            <motion.span
              key={index}
              layout
              className={`h-1 rounded-full ${index === stepNumber - 1 ? "bg-v-accent" : "bg-v-line"}`}
              animate={{
                width: index === stepNumber - 1 ? 28 : 10,
                opacity: index === stepNumber - 1 ? 1 : 0.55,
              }}
              transition={spring}
            />
          ))}
        </div>

        <motion.div
          className="mt-5 flex flex-wrap items-center justify-between gap-3"
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...fade, delay: reduceMotion ? 0 : 0.16 }}
        >
          <button
            type="button"
            onClick={onSkip}
            className="cursor-pointer text-[13px] font-medium text-v-muted transition-colors duration-[120ms] hover:text-v-fg"
          >
            {skipLabel}
          </button>
          <div className="flex items-center gap-2">
            {stepNumber > 1 ? (
              <Button variant="outline" size="sm" onClick={onBack}>
                Back
              </Button>
            ) : null}
            <Button variant="dark" size="sm" onClick={onAdvance}>
              {advanceLabel}
            </Button>
          </div>
        </motion.div>
      </motion.div>
      </div>

      {arrow ? (
        <TourArrow
          from={arrow.from}
          to={arrow.to}
          bow={arrow.bow}
          stepKey={step.id}
          reduceMotion={reduceMotion}
        />
      ) : null}
    </motion.div>
  );
}
