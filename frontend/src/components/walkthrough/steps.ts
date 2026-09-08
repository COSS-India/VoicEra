import type { WalkthroughStep } from "./types";

/** Six-step onboarding lap around the dashboard — intro, sidebar rail, agent
 * creation, metrics philosophy, search toolbar, and profile footer. Tag new
 * targets with `data-tour="<id>"` and add a step here. */
export const WALKTHROUGH_STEPS: WalkthroughStep[] = [
  {
    id: "intro",
    page: "/dashboard",
    presentation: "intro",
    title: "VoicEra makes a phone call enough.",
    body: "Any citizen with any phone, speaking any of 22+ Indian languages, gets a service that actually understands them — no app, no form, no queue. This tour takes about forty seconds.",
  },
  {
    id: "sidebar-rail",
    page: "/dashboard",
    target: "sidebar-rail",
    title: "One rail, always within reach.",
    body: "Agents, numbers, knowledge, batches, history — plus members and integrations. It stays collapsed until you need it, and expands the moment you point at it.",
    cardPlacement: "right-of-target",
    arrowFrom: "left",
    targetAnchor: "left-edge",
    arrowBow: -0.36,
  },
  {
    id: "new-agent-button",
    page: "/dashboard",
    target: "new-agent-button",
    title: "Agents start as a sentence.",
    body: "Describe the call in plain words. VoicEra drafts the script, chooses the voice and dialect, and hands you a number you can ring in under a minute.",
    cardPlacement: "bottom-right",
    arrowFrom: "logo",
    targetAnchor: "bottom-center",
    arrowBow: 0.32,
  },
  {
    id: "metrics-intro",
    page: "/dashboard",
    presentation: "intro",
    title: "We measure being understood.",
    body: "Everyone else counts minutes. Your headline number is how many callers got an answer without repeating themselves — the only metric a public service can be judged on.",
  },
  {
    id: "agents-search-toolbar",
    page: "/dashboard",
    target: "agents-search-toolbar",
    title: "Find anything, your way.",
    body: "Search by name, number or language. Filter by state. Switch between cards and a dense list — the choice sticks for next time. You can also press CTRL+K to quickly search and navigate using the keyboard.",
    cardPlacement: "below-target",
    arrowFrom: "top",
    targetAnchor: "top-center",
    arrowBow: -0.26,
  },
  {
    id: "sidebar-profile",
    page: "/dashboard",
    target: "sidebar-profile",
    title: "You, your org, your theme.",
    body: "Your profile, your organisation's members and invites, and light or dark — all from the bottom of the rail. Replay this walkthrough from here whenever you like.",
    cardPlacement: "above-target",
    arrowFrom: "bottom-left",
    targetAnchor: "center",
    arrowBow: 0.22,
  },
];
