---
title: Dashboard tour
description: A tour of the dashboard's pages.
---

Every screen in the dashboard, what it shows, and which API endpoints back it. A few screens are still stubs or sample data — this page says which, so you do not mistake either for your own.

<Warning>
The dashboard container runs Next.js in **development** mode with the source bind-mounted. That is right for local work and wrong for anything user-facing — see [Production deployment](../../guides/deployment/production).
</Warning>

## The layout shell

Every signed-in route lives under the `(app)` route group and shares one layout, `frontend/src/app/(app)/layout.tsx`. It wraps the page in two things:

* **`AuthProvider.tsx`** — the auth gate. On mount it reads the session from `localStorage` and calls `GET /users/me`. No stored session, or a failed call, and it clears storage and redirects to `/`. Children never render without a session, so no page needs its own auth check. It also merges the organisation name into the stored session so the sidebar can show it.
* **`AppSidebar.tsx`** — a collapsible nav rail, its expanded state persisted in `localStorage` under `voicera_sidebar_expanded`. It groups routes into **Build** (Agents, Numbers, Knowledge Base, Campaigns, History, Analytics, Telemetry) and **Workspace** (Members, Integrations), with a Walkthrough link and a profile menu in the footer.

Note that the sidebar does not link to `/agent-creation`, `/components`, or `/account` — those are reached from within pages or from the profile menu.

`PageHeader.tsx` is a shared eyebrow-plus-title-plus-description header. Only the UI-kit pages use it; the main dashboard screens write their own headers.

Sign-in and signup sit outside the shell at `/` and `/signup`, backed by `POST /users/login` and `POST /users/signup`.

## At a glance

| Route | Status | Backed by |
| --- | --- | --- |
| `/dashboard` | Live | `GET /agents`, `GET /calls/org/{org_id}` |
| `/agent-creation` | Live | `GET /configuration/*`, `GET /auth/configured`, `POST /agents` |
| `/agents/{agentId}/edit` | Live | `GET /agents/{id}`, `PATCH /agents/{id}` |
| `/numbers` | Live | `GET /phone-numbers`, attach/detach, provider inventory |
| `/history` | Live | `GET /calls/org/{org_id}`, recording and transcript blobs |
| `/members` | Live | `GET /members/{org_id}`, invite, assign-admin, remove |
| `/integrations` | Live | `GET /auth/catalog`, `GET /auth/configured`, `POST /auth` |
| `/account` | Live | `GET /users/me`, `GET /users/organisations`, switch-organisation |
| `/batches` | Live | `GET /campaign/`, `POST /campaign/upload`, `POST /campaign/create`, start/pause/resume/redial, `GET /campaign/{id}/runs`, `GET /agents` |
| `/knowledge-base` | Live | `GET /knowledge`, `POST /knowledge/upload`, `DELETE /knowledge/{id}` |
| `/analytics` | Live | `GET /calls/org/{org_id}/analytics` |
| `/telemetry` | Live | `GET /calls/{call_id}/metrics`, `GET /calls/{call_id}`, `GET /calls/org/{org_id}` |
| `/components` | Internal | Nothing — UI kit |
| `/walkthrough` | **Placeholder** | Nothing — the real onboarding tour is a separate overlay, not this route. See [walkthrough](#walkthrough) below. |

## dashboard

The agents home, rendered by `AgentsHome.tsx`. It lists every agent in your active organisation from `GET /agents`, and pulls up to 500 recent calls with `GET /calls/org/{org_id}` to show per-agent activity alongside each card.

Each card shows the agent's name, its purpose (derived from the first sentence of its system prompt by `agentPurposeFromApi()`), and either its linked phone number or a WebSocket badge. The distinction is read from `agent_category` directly, never guessed from whether a number field is populated.

The card's test action branches on that same field, and this is the most useful thing to understand about the page:

* A **`telephony`** agent opens `TestCallSheet.tsx` — you type an E.164 number and it fires `POST /calls/outbound`, placing a real phone call from the agent's linked number.
* A **`websocket`** agent opens `AgentTestModal.tsx` — a live browser microphone call over the runtime WebSocket. See [Browser test calls](test-calls).

The page can also duplicate an agent (`GET /agents/{id}` then `POST /agents` with the copied config) and delete one (`DELETE /agents/{id}`). A **History** item on the same card menu routes to [`/history?agent={agent_id}`](#history), pre-filtered to that agent's calls.

## agents/[agentId]/edit

Loads one agent with `GET /agents/{agent_id}`, runs it through `agentToForm()` to rebuild the wizard's flat form shape, and renders the same step components the wizard uses — `NameStep`, `LanguageProvidersStep`, `DeliveryStep`, `PromptKnowledgeStep`, and `ReviewStep`, with `SectionNav` down the side. `ReviewStep` does the saving, calling `updateAgent()` for an existing agent, which sends `PATCH /agents/{agent_id}`.

Because it shares the wizard's mapper, it shares the wizard's gaps. See [Agent creation wizard](agent-wizard).

## agent-creation

The six-step wizard. It has its own page: [Agent creation wizard](agent-wizard).

## numbers

Phone number inventory, rendered by `PhoneNumbers.tsx` over the `usePhoneNumbers` hook.

| Action | Endpoint |
| --- | --- |
| List the organisation's numbers | `GET /phone-numbers` |
| List numbers on a provider account not yet imported | `GET /phone-numbers/providers/{provider}/inventory` |
| Import a number, optionally linking it to an agent | `POST /phone-numbers/attach` |
| Unlink from its agent and from the provider | `DELETE /phone-numbers/detach` |

Each row carries an audit line built from `last_link_action`, `last_link_by_email`, and `last_link_at` — who attached, detached, or imported the number and when. Detaching keeps the inventory row; it only breaks the agent link and the provider-side binding. Background in [Telephony model](../../guides/concepts/telephony-model).

## batches

The route is `/batches`; the sidebar labels it **Campaigns**. Rendered by `Campaigns.tsx` over the `useCampaigns` hook and `frontend/src/lib/api/campaigns.ts`.

It lists `GET /campaign/`, uploads a contact CSV with `POST /campaign/upload` (parsed in the browser by `d3.csvParse` for a preview), creates with `POST /campaign/create`, and drives each campaign with `POST /campaign/{id}/start`, `/pause`, `/resume`, and `/redial`. Expanding a campaign fetches its per-contact attempts from `GET /campaign/{id}/runs`. Agents for the create form come from `GET /agents`.

Because dialling runs server-side, the hook polls the list so progress bars and states stay live without a reload.

Background: [Running a campaign](../../guides/operator/running-a-campaign) and [Campaigns](../../guides/concepts/campaigns).

## history

The one screen where the dashboard clearly beats the API, rendered by `History.tsx`.

It pages through `GET /calls/org/{org_id}` twenty rows at a time, joins each call to its agent (`GET /agents`), and lets you filter by date range (a preset or a custom from/to), call type, status — `completed`, `failed`, `in_progress`, `ringing`, `initiated` — and agent. All of it filters the current 20-row page in the browser; none of these are query parameters on the API call, so a filter can only narrow what you already fetched, not search the organisation. Phone numbers are masked in the list by `maskPhoneNumber()`. Opening **History** from an agent's card menu on [dashboard](#dashboard) routes here with `?agent={agent_id}`, which pre-selects that agent in the filter.

The **Export** menu has four options, all built on `frontend/src/lib/report.ts`: CSV or PDF of the currently filtered page, a CSV of every transcript in the organisation (via `listAllOrgCalls()`, a hundred rows at a time, plus one `GET /calls/{call_id}/transcript` per call), and a CSV scoped to whichever agent is selected in the filter.

Clicking a row opens `CallDetailSheet.tsx`, which fetches two things:

* `GET /calls/{call_id}/recording` — an authenticated proxy in front of MinIO. It is fetched as a blob because `<audio src>` cannot send an `Authorization` header; the sheet builds an object URL for playback and decodes the same blob for the waveform.
* `GET /calls/{call_id}/transcript` — parsed by `frontend/src/lib/transcript.ts` into `[timestamp] role: content` lines.

Transcript lines are anchored so the first line is t=0 and later lines are offset by their deltas. There is no shared clock between the transcript's timestamps and the recording's start, so the alignment between text and audio is a close estimate rather than an exact sync.

Browser test calls appear here alongside telephony calls. The browser registers the `call_type: web` CallLog itself with `POST /calls/web` before opening the socket, and the call gains a transcript and recording like any other.

A **View Call Telemetry** button in the sheet links to [`/telemetry?call={call_id}`](#telemetry) — disabled with a tooltip when the call has no latency data yet, since a call still in progress or one the runtime never wrote metrics for would otherwise deep-link into a 404.

## knowledge-base

`KnowledgeBase.tsx` runs over the `useKnowledgeBase` hook and `frontend/src/lib/api/knowledge.ts`: `GET /knowledge` to list, `POST /knowledge/upload` to add a document, and `DELETE /knowledge/{document_id}` to remove one. The client refuses a file over 25 MB before uploading, matching `KB_MAX_UPLOAD_BYTES` on the API.

Each `FileCard` has an **Eye** action that fetches `GET /knowledge/{document_id}/preview` as a blob (`previewKnowledgeDocument()`) and opens `PdfPreviewSheet.tsx`, a slide-in viewer built from an object URL. Both components are preview-source-agnostic — `FileCard` only ever emits `onPreview`, and the sheet only ever renders whatever `blob` it is handed — so `KnowledgeBase.tsx` is the only place that knows the source is this specific endpoint.

Ingestion and embedding happen server-side, so the hook polls while any document is still indexing and the Indexed / Indexing / Failed counts reflect real document status.

The wizard's knowledge-base picker calls the same `GET /knowledge`, so the documents you attach to an agent are your real ones.

Background: [Managing knowledge documents](../../guides/operator/managing-knowledge) and [Knowledge base (RAG)](../../guides/concepts/knowledge-base-rag).

## members

Fully wired, over the `useMembers` hook and `frontend/src/lib/api/members.ts`.

| Action | Endpoint | Who can |
| --- | --- | --- |
| List members | `GET /members/{org_id}` | Any member |
| Add a member | `POST /members/invite` | `admin`, `super_admin` |
| Promote to admin | `POST /members/assign-admin` | `super_admin` |
| Remove from the organisation | `POST /members/remove` | `super_admin` |

Cards sort highest-rank-first: `super_admin`, then `admin`, then `member`. There is no accept-invite step — `POST /members/invite` creates the account directly in your active organisation with a password you set, so you hand the credentials over yourself. The "add member" link the modal generates points at `/add-member/{uid}`, a shareable page identifier; the organisation context travels in query parameters. Roles are explained in [Multi-tenancy and roles](../reference/multi-tenancy).

## integrations

The credential manager, rendered by `Integrations.tsx`. It is the screen you need before the wizard is usable, because the wizard hides every provider you have not configured here.

`GET /auth/catalog` returns each provider's field schema — types, descriptions, examples, and which fields are secret. `groupProvidersByKind()` buckets them into STT, TTS, LLM, and telephony sections, with providers that serve several kinds appearing in each. `GET /auth/configured` marks which are already connected.

A second filter row sits above the list: provider type tabs (`cloud`, `adapter`, `local`), built from whatever `catalog.provider_type` values are actually present, on top of the existing kind filter. Both narrow the same connected/available/telephony lists together.

Saving a provider sends `POST /auth` with `{ provider, auth }`. `GET /auth/{provider}` reads a stored entry back and `DELETE /auth/{provider}` removes it. Secret fields render behind a show/hide toggle. Credentials are encrypted at rest by the API — see [Provider credentials (ProviderAuth)](../reference/provider-auth).

Because the form is generated from the catalog rather than hand-written, it always matches what the API accepts. That makes this screen genuinely more reliable than reading credential field names out of documentation.

## analytics

Organisation-wide call volume, rendered by `Analytics.tsx` from a single request: `GET /calls/org/{org_id}/analytics`.

This is what separates the screen from [dashboard](#dashboard) and [telemetry](#telemetry). Those two pull raw call logs with `GET /calls/org/{org_id}` and aggregate in the browser; this one asks the API for figures already aggregated server-side, so it counts every call in the organisation rather than only the page it fetched — [dashboard](#dashboard) sees at most 500.

The layout is four stat tiles over two panels:

| Tile | Field |
| --- | --- |
| Calls Attempted | `calls_attempted` |
| Calls Connected | `calls_connected`, noted with `trend_vs_last_week_pct` |
| Avg Call Duration | `average_duration_seconds` |
| Total Minutes | `total_duration_seconds` |

**Agent Performance** is a recharts bar chart of `agent_performance` with a list toggle — the API caps that array at the ten busiest agents, so it is a leaderboard rather than a full breakdown. **Connection Breakdown** shows `connection_rate` as a headline percentage and progress bar, with `calls_connected` and `calls_failed` beneath it. **Model Usage** shows the single busiest STT, TTS, and LLM model from `model_usage`, each as a bar sized against the others' call counts — a stage renders blank if the API returned `null` for it. A refresh button sits next to the Connection Breakdown headline; clicking it re-fetches and stamps an "Updated …" timestamp beside it.

**Download PDF**, top right, builds a real PDF client-side with `frontend/src/lib/report.ts` (a thin `jsPDF` wrapper) — vector bars for Agent Performance, Connection Breakdown, and Model Usage, not a screenshot or `window.print()`. Every exported PDF and CSV in the app opens with the same organisation / downloaded-by / generated-at header from that same module, so a report is traceable back to who pulled it.

One caveat worth knowing before reading the numbers: the figures are **all-time**, with no date-range or per-agent filter anywhere on the screen. And "connected" counts only calls whose `call_response` is `answered`, which is also the population the duration figures average over — so Avg Call Duration is per answered call, not per attempt. See [`GET /calls/org/{org_id}/analytics`](../../api-reference/calls) for the response shape.

For per-call pipeline latency rather than volume, use [telemetry](#telemetry).

`Languages.tsx` draws a d3 bubble map — scaled circles over a colour ramp — from the static `LANGS_GEO` array in `dashboard-data.ts`. Those are sample figures, not your call volumes, and no screen currently renders the component.

## telemetry

Per-call pipeline latency, rendered by `Telemetry.tsx` from the [CallMetrics](../../api-reference/calls) the runtime writes at the end of every call.

Pick a call — or deep-link one with `?call={call_id}` — and the screen fetches `GET /calls/{call_id}` and `GET /calls/{call_id}/metrics`, with `GET /calls/org/{org_id}` behind the picker. It shows four averages as stat tiles, each tinted against a threshold and compared against the previous call:

| Tile | Warn | Bad |
| --- | --- | --- |
| Avg STT | 800 ms | 1500 ms |
| Avg LLM TTFB | 1500 ms | 2500 ms |
| Avg TTS 1st chunk | 500 ms | 1000 ms |
| Avg round trip | 3000 ms | 5000 ms |

Below them, a recharts bar chart and a table share one per-turn dataset — hovering either highlights the same turn in both — and **Export CSV** writes the per-turn rows out, via the same `report.ts` helper the other two screens use.

A call has no metrics until the runtime finishes writing them, so `GET .../metrics` returns `404` for a call still in progress; the screen treats that as "no data" rather than an error.

## account

Your profile and organisation switcher, rendered by `Account.tsx`. It loads `GET /users/me` and `GET /users/organisations` in parallel, and switching organisation calls `POST /users/switch-organisation` and writes the returned token back to `localStorage`, so the whole dashboard re-scopes to the new organisation.

`frontend/src/lib/api/organisations.ts` also exposes `DELETE /organisations/{org_id}`, restricted by the API to a `super_admin` acting on their own active organisation.

## components

Internal. A UI-kit gallery of every shared primitive — buttons, inputs, cards, badges, switches, spinners, progress bars, tooltips, toasts, modals, the stepper, the nav rail — each shown with its variants. It is a developer reference for the design system, not a product feature. Nothing here reads or writes data.

## walkthrough

The `/walkthrough` route itself is still the placeholder stub described above — but the sidebar's "Walkthrough" footer button does not link to it. It calls `restartWalkthrough()` and navigates to `/dashboard`, because the real product tour is `WalkthroughOverlay.tsx`, a spotlight-and-arrow overlay drawn on top of whichever page it targets, not a route of its own.

`frontend/src/components/walkthrough/` holds the whole feature:

* **`WalkthroughProvider.tsx`** wraps the `(app)` layout, holds `active`/`stepIndex` state, and decides whether to render the overlay by comparing the current step's `page` field against `usePathname()`.
* **`steps.ts`** defines six fixed steps, all on `/dashboard`: an intro card, the sidebar rail, the "new agent" button, a second intro card about metrics, the search toolbar, and the sidebar profile footer. Each non-intro step spotlights one element tagged `data-tour="<id>"` in the DOM.
* **`WalkthroughOverlay.tsx`** renders one step at a time — a dimmed backdrop with a cut-out spotlight around the target (or a centered card with no spotlight for intro steps), a curved dashed arrow with animated dots from the card to the target, and Back / Next / Skip controls. Motion respects `prefers-reduced-motion`.
* **`storage.ts`** persists progress in `localStorage` under `voicera_walkthrough_pending`, `voicera_walkthrough_active`, and `voicera_walkthrough_step` — nothing is stored server-side or on the user record.

**What triggers it:** `SignInPage` (`frontend/src/app/page.tsx`) and the signup page (`frontend/src/app/signup/page.tsx`) both call `markWalkthroughPending()` when the login/signup response has `is_first_login: true`. That only sets a `localStorage` flag; the tour itself starts on the next mount of the `(app)` layout, which `WalkthroughProvider` picks up in a `useEffect` that consumes the pending flag and starts the tour from step 0. A page reload mid-tour resumes from whatever step was last written, rather than restarting.

**Replaying it:** the sidebar footer's "Walkthrough" button (`AppSidebar.tsx`) calls `restart()` from `useWalkthrough()` and routes to `/dashboard`, which restarts the same six steps from the beginning — this is the mechanism steps.ts's final card means by "Replay this walkthrough from here."

It is fully skippable (**Skip the tour** / **Skip the rest**, depending on step) and steppable (Back once past step 1, Next/Finish otherwise), and skipping or finishing clears the `localStorage` state the same way. There is no server-side "has seen onboarding" flag — only the client-visible `is_first_login` response field decides whether it auto-starts, and only `localStorage` remembers progress or that it was skipped.

## Real features versus scaffolding

Being blunt about it, because the sidebar gives all of these equal weight:

* **Genuine, API-backed features:** Agents home, agent creation, agent edit, Numbers, History, Members, Integrations, Account, Campaigns, Knowledge Base, Analytics, Telemetry.
* **Genuine, but not API-backed:** the onboarding walkthrough (`WalkthroughOverlay.tsx`) — a real, fully-built six-step tour triggered on first login/signup and replayable from the sidebar. It is client-only: everything it needs lives in `localStorage`, with no server persistence and no route of its own. See [walkthrough](#walkthrough) above.
* **Screens that look complete but are sample data:** the language map (`Languages.tsx`), which renders a convincing bubble chart from a hardcoded array and is not currently reachable from any screen. Do not read it as your data.
* **Placeholders:** the `/walkthrough` route — a single card admitting the feature is not built at that URL. Do not confuse it with the real overlay above; they share a name and nothing else.
* **Developer scaffolding:** `/components` is a UI-kit page, self-described as such. It is unlinked from the sidebar and safe to ignore. The standalone `/library` prompt-module browser was removed; the same nine modules are still reachable from the wizard's [prompt library dialog](agent-wizard#the-prompt-library).

One more piece of scaffolding worth knowing about: `frontend/src/app/api/` contains three Next.js route handlers (`/api/agents`, `/api/auth/login`, `/api/auth/signup`) whose own comments call them "a UI-kit demo, not wired to a real database" — one keeps agents in a module-level array that resets on restart, the others return a mock user and a fake token. The live dashboard does not call them; real auth goes to the API's `/users/login` and `/users/signup`. Do not mistake them for a backend.

## Related

* [Overview](overview)
* [Running the dashboard](running)
* [Agent creation wizard](agent-wizard)
* [Browser test calls](test-calls)
* [Calls and call artifacts](../../guides/concepts/calls)
* [REST API](../../api-reference/overview)
