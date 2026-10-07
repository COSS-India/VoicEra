# Call-metrics latency fixes — `deployment-bluedots`

**Status:** PoC-branch fix. This file, and the code it documents, is meant to be
discarded along with the rest of this branch once the underlying question
(bluedots deployment feasibility) is answered. It stays in the branch rather
than in the permanent `docs/` site because it's an investigation record, not
a durable guide.

**Why this exists:** testing feedback from the field (WhatsApp, 2026-10-07)
reported the call-metrics dashboard giving wrong or missing numbers:

1. MKS: "LLM TTFB reads 7–9ms in the dashboard. That's our first SSE chunk,
   the standard OpenAI role chunk (`delta: {"role":"assistant","content":""}`),
   sent before we call the model — it'll always be a few ms. Measure to the
   first chunk that actually carries content."
2. Kislaya: "Only one turn per call has STT/LLM TTFB/TTS captured; the rest
   show as 'bot-initiated' with nothing recorded." And, on a second fresh
   call: "no stage data at all — all four tiles blank, every turn
   'bot-initiated', Export CSV disabled."

A third, related bug behind the "all tiles blank" symptom was found and
fixed separately, directly on this branch, in `70e1a62` ("fix: backfill
empty CallMetrics placeholder instead of discarding real metrics"): a
telephony reconnect could flush a transport-only placeholder doc before any
turn completed, and strict write-once then silently discarded the real
metrics from the run that actually finished the call. That fix lives in
`apps/api/app/services/call_metrics_service.py` / `apps/api/app/routers/calls.py`
and doesn't overlap with anything below — noted here only so this file stays
a complete picture of the "4 blank tiles" investigation, not because this
file's fix depends on it.

The two bugs below turned out to be real, and both are inside
`pipecat-ai==1.8.1` (the vendored dependency, `dist-packages`), not in
VoicERA's own code. Since patching `dist-packages` directly doesn't survive
a redeploy or `pip install`, both are fixed from VoicERA's side instead, by
replacing the stock `UserBotLatencyObserver` with a thin subclass in
`observers.py` — `_CorrectedUserBotLatencyObserver`.

## What's actually wrong, and where

### Bug 1 — LLM "TTFB" measures stream-open, not first content token

`pipecat/services/openai/base_llm.py`, `BaseOpenAILLMService._process_context()`:

```python
if chunk.choices is None or len(chunk.choices) == 0:
    continue
await self.stop_ttfb_metrics()        # ← fires here, on ANY chunk with choices
if not chunk.choices[0].delta:
    continue
...
elif chunk.choices[0].delta.content:
    await self._push_llm_text(chunk.choices[0].delta.content)
```

`stop_ttfb_metrics()` stops the timer and pushes a `MetricsFrame` on the
**first** streamed chunk that has any `choices` at all — before checking
whether `delta.content` is non-empty. For an OpenAI-compatible chat
completion, the first SSE chunk is always the empty role-preamble
(`delta: {"role":"assistant","content":""}`), which the server sends the
instant the stream opens, before the model has produced anything. So the
"LLM TTFB" pipecat reports is network/proxy round-trip to the first SSE
event, not model latency — exactly MKS's diagnosis.

Pipecat does have the metric that was actually wanted — `TTFATMetricsData` /
`stop_ttfat_metrics()`, documented as "time to first answer token... the
caller sees" — but in `_process_context`, `stop_ttfat_metrics()` is only
called in the tool-call branch (line ~513), never in the plain-text-content
branch (line ~541). So for ordinary conversational turns, that better metric
is never emitted. This looks like a gap in pipecat 1.8.1 worth reporting
upstream; not something to wait on for this branch.

### Bug 2 — turns with real user speech show up "bot-initiated" with no stage data

`pipecat/observers/user_bot_latency_observer.py`, `UserBotLatencyObserver`:

```python
def _reset_accumulators(self):
    self._ttfb = []
    self._text_aggregation = None
    self._user_turn_start_time = None   # cleared
    self._user_turn = None
    self._function_call_starts = {}
    self._function_call_metrics = []
    # _user_stopped_time is NOT cleared here
```

`_reset_accumulators()` runs on `InterruptionFrame` (a genuine barge-in, not
every turn). It wipes `_ttfb` (the per-stage STT/LLM/TTS breakdown) and
`_user_turn_start_time`, but leaves `_user_stopped_time` untouched. If an
`InterruptionFrame` lands anywhere between a real `VADUserStoppedSpeakingFrame`
and the `BotStartedSpeakingFrame` that follows, the next
`_handle_bot_started_speaking()` still finds `_user_stopped_time is not None`
and reports a real `on_latency_measured` ("user_to_bot_secs") number — against
a breakdown whose `ttfb` list and `user_turn_start_time` were just wiped.

Both the backend (`apps/api/app/services/call_metrics_service.py`,
`_with_avg_latency`) and the frontend (`frontend/src/lib/call-metrics.ts`,
`normalizeCallMetrics`) treat `breakdown.user_turn_start_time == null` as "no
real user turn → bot-initiated, exclude from averages." So a turn where the
user genuinely spoke, then briefly overlapped the bot's speech (Hindi/Indic
backchanneling like "haan" / "theek hai" while the bot is still talking is a
very plausible trigger for VoicERA's outbound-call audio), loses its stage
data and gets mislabeled bot-initiated — even though real latency was
measured for it.

This also explains an earlier, previously-unexplained finding from this same
debugging session: a call where `user_turn_start_time` came back `null` for
every turn despite real `user_to_bot_secs` values existing. Same root cause.

## The fix — `apps/runtime/services/pipecat/metrics/observers.py`

`_CorrectedUserBotLatencyObserver` subclasses pipecat's `UserBotLatencyObserver`
and overrides three things:

- **`_reset_accumulators()`**: also clears `_user_stopped_time` (and the new
  LLM-content-TTFB tracking state below) on every reset — including on
  `InterruptionFrame` — so a cancelled cycle can never be reported against
  whatever bot utterance follows it. Fixes Bug 2.
- **`on_push_frame()`**: tracks `LLMFullResponseStartFrame` (pushed the
  instant the LLM call begins) through to the first `LLMTextFrame` carrying
  non-empty text (the first real output token), and records that gap.
- **`_handle_bot_started_speaking()`**: just before the base class builds and
  emits the per-turn breakdown, patches any LLM-stage TTFB entry already in
  `self._ttfb` with the tracked content-TTFB gap, replacing pipecat's
  stream-open number. Fixes Bug 1.

The patch has to happen at `BotStartedSpeakingFrame` time rather than when
the (wrong) `TTFBMetricsData` first arrives, because pipecat pushes that
metrics frame on the empty preamble chunk — **before** the real content
chunk exists — so the correct value isn't known yet at the moment the wrong
one would need patching. By the time the bot actually starts speaking, the
LLM has long since finished streaming its answer, so the tracked value is
reliably available. All of this runs inside one observer's own frame queue
(see `pipecat/pipeline/worker_observer.py` — each observer gets an
independent `asyncio.Queue` processed strictly in arrival order), so there's
no race between "the wrong TTFB arrived," "the right content token arrived,"
and "the bot started speaking": they're handled in that order, synchronously,
one queue, no cross-observer timing to reason about.

Nothing else changes. No new API fields, no frontend changes, no schema
changes — every existing consumer (the dashboard tiles, the per-turn table,
CSV export, the backend's `avg_llm_secs`) reads the same
`latencies.breakdowns[].ttfb[]`/`user_turn_start_time` fields it always did;
they just now get correct values.

**Known limitation:** `LLMFullResponseStartFrame`/`LLMTextFrame` don't carry
a processor identity, so Bug 1's fix assumes a single active LLM processor
per call. True for every VoicERA agent today; would need rework for a
pipeline running two concurrent LLM stages.

## Verification

- `apps/runtime/tests/test_call_metrics_observers.py` (new): simulates the
  exact frame sequences from both bugs against the real pipecat 1.8.1
  classes and asserts the corrected behavior.
- `apps/runtime/tests/test_call_metrics_writer.py`,
  `apps/api/tests/test_call_metrics.py` (pre-existing): re-ran unchanged,
  still pass — confirms nothing downstream of the writer/API broke.

To re-verify against a live call once deployed: run a call with at least one
turn, check that the "Avg LLM TTFB" tile reads a plausible number (hundreds
of ms to a few seconds, not single-digit ms), and that a turn where the
tester spoke and briefly talked over the bot still shows up with its
STT/LLM/TTS stage data intact rather than "bot-initiated."

## What we deliberately did not do

- **Not patched `dist-packages`/pipecat directly** — doesn't survive a
  redeploy, and this branch may get rebuilt from a clean image.
- **Not filed upstream with pipecat/Daily yet** — worth doing regardless of
  what happens to this branch, since Bug 1 and Bug 2 are both real defects
  in `pipecat-ai==1.8.1` independent of VoicERA. Not done as part of this
  fix because it doesn't unblock today's testing.
- **Not touched the frontend or the API response schema** — the fix is
  entirely upstream of both, at the point metrics are collected, so nothing
  downstream needed to change.
