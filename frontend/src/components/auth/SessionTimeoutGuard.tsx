"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { clearSession } from "@/lib/auth-storage";
import {
  broadcastSession,
  clearActivityTracking,
  getLastActivityAt,
  markSessionExpiredForLogin,
  msUntilExpiry,
  openSessionChannel,
  shouldExpire,
  shouldShowWarning,
  touchActivity,
  type SessionBroadcast,
} from "@/lib/session-timeout";

const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = [
  "pointerdown",
  "keydown",
  "touchstart",
  "click",
  "scroll",
];

/** Throttle writes so high-frequency scroll/pointer events don't thrash storage. */
const TOUCH_THROTTLE_MS = 1000;
/** How often to re-evaluate inactivity / expiry. */
const TICK_MS = 1000;

function expireAndRedirect() {
  clearSession();
  clearActivityTracking();
  markSessionExpiredForLogin();
  broadcastSession({ type: "expired" });
  if (typeof window !== "undefined" && window.location.pathname !== "/") {
    // Hard redirect: force a full client reset outside React routing.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/";
  }
}

/**
 * Watches authenticated user activity across tabs. After 1 hour of inactivity
 * shows a warning; after 5 more minutes without resume, clears the session
 * and sends the user to login with an expiry message.
 */
export function SessionTimeoutGuard() {
  const [warningOpen, setWarningOpen] = useState(() => {
    if (typeof window === "undefined") return false;
    const existing = getLastActivityAt();
    return existing ? shouldShowWarning(existing) : false;
  });
  const [secondsLeft, setSecondsLeft] = useState(() => {
    if (typeof window === "undefined") return 5 * 60;
    const existing = getLastActivityAt();
    if (!existing) return 5 * 60;
    return Math.max(0, Math.ceil(msUntilExpiry(existing) / 1000));
  });
  const lastTouchWrite = useRef(0);
  const warningOpenRef = useRef(warningOpen);

  useEffect(() => {
    warningOpenRef.current = warningOpen;
  }, [warningOpen]);

  const recordActivity = useCallback((opts?: { force?: boolean; broadcast?: boolean }) => {
    const now = Date.now();
    if (!opts?.force && now - lastTouchWrite.current < TOUCH_THROTTLE_MS) return;
    lastTouchWrite.current = now;
    touchActivity(now);
    if (opts?.broadcast !== false) {
      broadcastSession({ type: "activity", at: now });
    }
    if (warningOpenRef.current) {
      setWarningOpen(false);
      broadcastSession({ type: "continue" });
    }
  }, []);

  const continueSession = useCallback(() => {
    recordActivity({ force: true });
    setWarningOpen(false);
    broadcastSession({ type: "continue" });
  }, [recordActivity]);

  useEffect(() => {
    // Seed activity on mount so a fresh login / page load starts the 1h clock.
    const existing = getLastActivityAt();
    if (!existing) {
      touchActivity();
    } else if (shouldExpire(existing)) {
      expireAndRedirect();
      return;
    }

    const onActivity = () => recordActivity();
    for (const ev of ACTIVITY_EVENTS) {
      window.addEventListener(ev, onActivity, { passive: true, capture: true });
    }
    const onVisibility = () => {
      if (document.visibilityState === "visible") recordActivity();
    };
    document.addEventListener("visibilitychange", onVisibility);

    const channel = openSessionChannel();
    const onBroadcast = (ev: MessageEvent<SessionBroadcast>) => {
      const msg = ev.data;
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "activity" || msg.type === "continue") {
        lastTouchWrite.current = Date.now();
        setWarningOpen(false);
      } else if (msg.type === "expired") {
        clearSession();
        clearActivityTracking();
        markSessionExpiredForLogin();
        if (window.location.pathname !== "/") {
          // eslint-disable-next-line @next/next/no-location-assign-relative-destination
          window.location.href = "/";
        }
      }
    };
    channel?.addEventListener("message", onBroadcast);

    // storage event covers tabs that don't share BroadcastChannel (rare) and
    // keeps last-activity in sync when another tab writes localStorage.
    const onStorage = (e: StorageEvent) => {
      if (e.key !== "voicera_last_activity" || e.newValue == null) return;
      lastTouchWrite.current = Date.now();
      setWarningOpen(false);
    };
    window.addEventListener("storage", onStorage);

    const tick = window.setInterval(() => {
      const last = getLastActivityAt() ?? Date.now();
      if (shouldExpire(last)) {
        expireAndRedirect();
        return;
      }
      if (shouldShowWarning(last)) {
        setWarningOpen(true);
        setSecondsLeft(Math.max(0, Math.ceil(msUntilExpiry(last) / 1000)));
      } else {
        setWarningOpen(false);
      }
    }, TICK_MS);

    return () => {
      for (const ev of ACTIVITY_EVENTS) {
        window.removeEventListener(ev, onActivity, true);
      }
      document.removeEventListener("visibilitychange", onVisibility);
      channel?.removeEventListener("message", onBroadcast);
      channel?.close();
      window.removeEventListener("storage", onStorage);
      window.clearInterval(tick);
    };
  }, [recordActivity]);

  if (!warningOpen) return null;

  const mins = Math.floor(secondsLeft / 60);
  const secs = secondsLeft % 60;
  const countdown =
    mins > 0 ? `${mins}:${secs.toString().padStart(2, "0")}` : `${secs}s`;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-[var(--v-overlay)] p-6"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="session-inactive-title"
      aria-describedby="session-inactive-desc"
    >
      <div className="animate-v-rise flex w-full max-w-md flex-col overflow-hidden rounded-v-md border border-v-line bg-white shadow-2xl">
        <div className="flex flex-col gap-1 border-b border-v-line px-5 py-4">
          <h2 id="session-inactive-title" className="m-0 text-[17px] font-semibold tracking-tight">
            Session Inactive
          </h2>
        </div>
        <div className="flex flex-col gap-4 p-5">
          <p id="session-inactive-desc" className="m-0 text-sm leading-relaxed text-v-muted-2">
            Your session has been inactive. For your security, your session will expire in 5
            minutes.
          </p>
          <p className="m-0 text-[13px] font-medium text-v-fg" aria-live="polite">
            Expires in {countdown}
          </p>
          <Button type="button" className="w-full justify-center" onClick={continueSession}>
            Continue Session
          </Button>
        </div>
      </div>
    </div>
  );
}
