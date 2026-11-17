/** Centralized session inactivity / lifetime constants and storage helpers.
 *
 * Active users keep a valid client session indefinitely while interacting —
 * the 1-hour value is the *inactivity* threshold before a warning, not a hard
 * logout clock. After the warning, a 5-minute grace period remains before
 * tokens are cleared and the user is sent to login.
 */

export const INACTIVITY_MS = 60 * 60 * 1000; // 1 hour without activity → warn
export const WARNING_GRACE_MS = 5 * 60 * 1000; // 5 minutes after warning → expire

const LAST_ACTIVITY_KEY = "voicera_last_activity";
const EXPIRED_FLAG_KEY = "voicera_session_expired";
const CHANNEL_NAME = "voicera_session";

export type SessionBroadcast =
  | { type: "activity"; at: number }
  | { type: "continue" }
  | { type: "expired" };

export function getLastActivityAt(): number | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(LAST_ACTIVITY_KEY);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function touchActivity(at = Date.now()): number {
  if (typeof window === "undefined") return at;
  localStorage.setItem(LAST_ACTIVITY_KEY, String(at));
  return at;
}

export function clearActivityTracking() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(LAST_ACTIVITY_KEY);
}

export function markSessionExpiredForLogin() {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(EXPIRED_FLAG_KEY, "1");
  } catch {
    /* private mode / blocked storage */
  }
}

/** Returns true once if the previous session expired due to inactivity. */
export function consumeSessionExpiredFlag(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const v = sessionStorage.getItem(EXPIRED_FLAG_KEY);
    if (v) sessionStorage.removeItem(EXPIRED_FLAG_KEY);
    return v === "1";
  } catch {
    return false;
  }
}

export function msUntilWarning(lastActivityAt: number, now = Date.now()): number {
  return lastActivityAt + INACTIVITY_MS - now;
}

export function msUntilExpiry(lastActivityAt: number, now = Date.now()): number {
  return lastActivityAt + INACTIVITY_MS + WARNING_GRACE_MS - now;
}

export function shouldShowWarning(lastActivityAt: number, now = Date.now()): boolean {
  const since = now - lastActivityAt;
  return since >= INACTIVITY_MS && since < INACTIVITY_MS + WARNING_GRACE_MS;
}

export function shouldExpire(lastActivityAt: number, now = Date.now()): boolean {
  return now - lastActivityAt >= INACTIVITY_MS + WARNING_GRACE_MS;
}

export function openSessionChannel(): BroadcastChannel | null {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return null;
  try {
    return new BroadcastChannel(CHANNEL_NAME);
  } catch {
    return null;
  }
}

export function broadcastSession(msg: SessionBroadcast) {
  const ch = openSessionChannel();
  if (!ch) return;
  try {
    ch.postMessage(msg);
  } finally {
    ch.close();
  }
}
