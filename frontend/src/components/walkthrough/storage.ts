/** Small localStorage-backed state machine for the walkthrough tour, so it
 * survives navigation between pages (dashboard -> agent-creation) and page
 * reloads. Kept separate from React so it can be triggered from outside the
 * (app) layout tree, e.g. right after login/signup. */

const PENDING_KEY = "voicera_walkthrough_pending";
const ACTIVE_KEY = "voicera_walkthrough_active";
const STEP_KEY = "voicera_walkthrough_step";

/** Call right after a login/signup response indicates this is the user's
 * first-ever login — the (app) layout picks this up on next mount. */
export function markWalkthroughPending(): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(PENDING_KEY, "1");
}

/** Reads and clears the pending flag in one step, so it's only ever consumed once. */
export function consumeWalkthroughPending(): boolean {
  if (typeof window === "undefined") return false;
  const pending = localStorage.getItem(PENDING_KEY) === "1";
  if (pending) localStorage.removeItem(PENDING_KEY);
  return pending;
}

export function readWalkthroughState(): { active: boolean; step: number } {
  if (typeof window === "undefined") return { active: false, step: 0 };
  return {
    active: localStorage.getItem(ACTIVE_KEY) === "1",
    step: Number(localStorage.getItem(STEP_KEY) ?? "0"),
  };
}

export function writeWalkthroughState(active: boolean, step: number): void {
  if (typeof window === "undefined") return;
  if (active) {
    localStorage.setItem(ACTIVE_KEY, "1");
    localStorage.setItem(STEP_KEY, String(step));
  } else {
    localStorage.removeItem(ACTIVE_KEY);
    localStorage.removeItem(STEP_KEY);
  }
}
