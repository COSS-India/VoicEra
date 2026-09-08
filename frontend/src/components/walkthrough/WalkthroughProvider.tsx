"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { AnimatePresence } from "framer-motion";
import { usePathname } from "next/navigation";
import { WALKTHROUGH_STEPS } from "./steps";
import { consumeWalkthroughPending, readWalkthroughState, writeWalkthroughState } from "./storage";
import { WalkthroughOverlay } from "./WalkthroughOverlay";

interface WalkthroughContextValue {
  active: boolean;
  /** Re-launch the tour from the first step (e.g. from a "Walkthrough" nav item). */
  restart: () => void;
  skip: () => void;
}

const WalkthroughContext = createContext<WalkthroughContextValue>({
  active: false,
  restart: () => {},
  skip: () => {},
});

export function WalkthroughProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);

  // Runs once per mount of the (app) layout — picks up a tour queued by
  // login/signup, or resumes one already in progress after a page reload.
  useEffect(() => {
    if (consumeWalkthroughPending()) {
      setActive(true);
      setStepIndex(0);
      writeWalkthroughState(true, 0);
      return;
    }
    const stored = readWalkthroughState();
    setActive(stored.active);
    setStepIndex(stored.step);
  }, []);

  function skip() {
    setActive(false);
    setStepIndex(0);
    writeWalkthroughState(false, 0);
  }

  function restart() {
    setActive(true);
    setStepIndex(0);
    writeWalkthroughState(true, 0);
  }

  function advance() {
    const next = stepIndex + 1;
    if (next >= WALKTHROUGH_STEPS.length) {
      setActive(false);
      setStepIndex(0);
      writeWalkthroughState(false, 0);
      return;
    }
    setStepIndex(next);
    writeWalkthroughState(true, next);
  }

  function back() {
    if (stepIndex <= 0) return;
    const prev = stepIndex - 1;
    setStepIndex(prev);
    writeWalkthroughState(true, prev);
  }

  const currentStep = active ? WALKTHROUGH_STEPS[stepIndex] : undefined;
  const showOnThisPage = Boolean(currentStep && currentStep.page === pathname);

  return (
    <WalkthroughContext.Provider value={{ active, restart, skip }}>
      {children}
      <AnimatePresence mode="wait">
        {showOnThisPage && currentStep ? (
          <WalkthroughOverlay
            key="walkthrough-overlay"
            step={currentStep}
            stepNumber={stepIndex + 1}
            totalSteps={WALKTHROUGH_STEPS.length}
            onAdvance={advance}
            onBack={back}
            onSkip={skip}
          />
        ) : null}
      </AnimatePresence>
    </WalkthroughContext.Provider>
  );
}

export function useWalkthrough() {
  return useContext(WalkthroughContext);
}
