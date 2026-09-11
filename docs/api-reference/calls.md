---
title: Calls
description: Place calls, register them, and fetch recordings and transcripts.
---

`apps/api/app/routers/calls.py`, prefix `/api/v1/calls`. See [Calls and call artifacts](../guides/concepts/calls).

## `POST /calls/outbound`

Bearer. `201`. Places a call and registers a `CallLog` with status `initiated`.

```json
{
  "agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "to_number": "+14155551234",
  "from_number": "+14155559999",
  "custom_variables": {
    "customer_name": "Jane Doe",
    "account_id": "ACC-123"
  }
}
```

`from_number` is an optional caller-ID override. `custom_variables` are merged over the agent's defaults at call time and substituted into the prompts — see [Agent configuration](../developer/reference/agent-configuration).

Returns `OutboundCallResponse`: `call_id`, `status`, `provider_call_sid`, `from_number`, `to_number`, `agent_id`, `custom_variables`.

## `POST /calls/inbound`

Bearer. `201`. The runtime calls this from the answer webhook, using a bot JWT.

```json
{
  "agent_id": "…",
  "provider_call_sid": "…",
  "from_number": "+14155551234",
  "to_number": "+14155559999"
}
```

Returns `InboundCallRegisterResponse`: `call_id`, `status`, `provider_call_sid`, `call_type`, `from_number`, `to_number`, `agent_id`.

## `POST /calls/web`

Bearer. `201`. Registers a browser websocket session so it gets a `CallLog` and artifacts. The agent must be `agent_category: websocket`.

```json
{
  "agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "custom_variables": {
    "customer_name": "Jane Doe"
  }
}
```

Returns `WebCallRegisterResponse`: `call_id`, `status`, `call_type` (always `web`), `agent_id`, `custom_variables`.

Calling this is optional. If a browser connects to `WS /agent/{org_id}/{agent_id}` with no `call_id`, the runtime registers one itself. Pre-register only when you need the `call_id` before the session starts — then pass it as `?call_id=` on the WebSocket URL. The runtime discards a `call_id` whose `call_type` is not `web` or whose `agent_id` does not match, and falls back to auto-creating one.

## `PATCH /calls/{call_id}` and `PATCH /calls/by-provider-sid/{provider_call_sid}`

Bearer. Both take the same partial body and return the same `CallLogResponse`. The by-SID variant exists for provider hangup callbacks, which know the SID and not the `call_id`.

```json
{
  "transcript_url": "minio://…",
  "recording_url": "minio://…",
  "end_time_utc": "2026-01-01T12:34:56+00:00",
  "status": "completed",
  "call_response": "answered"
}
```

Every field is optional, but an empty body returns `400 No fields to update` — only fields you actually set are applied.

`duration` is derived, never sent. When a patch carries `end_time_utc`, the service computes the duration from `start_time_utc` and clamps it at zero; a patch without `end_time_utc` has any `duration` stripped. The `minio://` URIs you write are rewritten in the response to the two proxy routes below.

## `GET /calls/{call_id}/recording` and `GET /calls/{call_id}/transcript`

Bearer. Stream the artifact out of MinIO through the API, so clients never need MinIO credentials. `404` when the call or the object is missing, `400` when the stored URL is not a usable object key.

## `GET /calls/{call_id}/metrics` and `PUT /calls/{call_id}/metrics`

Bearer (bot JWT supported). Pipeline metrics live in the separate `CallMetrics` collection — they are **not** returned by `GET /calls/{call_id}`.

`PUT` body (`CallMetricsBody`):

```json
{
  "summary": { "turn_count": 3, "interrupted_turn_count": 1, "user_bot_latency_avg_secs": 0.92 },
  "transport": { "client_connected_secs": 0.4 },
  "turns": [{ "turn_number": 1, "duration_secs": 12.5, "was_interrupted": false }],
  "latencies": {
    "first_bot_speech_secs": 2.1,
    "user_to_bot_secs": [0.85, 1.2],
    "breakdowns": []
  }
}
```

The runtime writes metrics at call end via `PUT`. Writes are **once per call** — a second `PUT` for the same `call_id` is ignored and returns the existing document. `GET` returns `404` when no metrics exist yet.

`GET` adds four fields to `summary` that are not in the stored document: `avg_stt_secs`, `avg_tts_secs`, `avg_llm_secs`, and `avg_latency_secs`, computed on the fly from `latencies.breakdowns`. Each stage average is `null` if that stage never appears in a breakdown; `avg_latency_secs` sums whichever stage averages are actually available rather than turning `null` the moment one stage is missing. Turns with no `user_turn_start_time` (bot-initiated, no real user turn) are excluded from all four.

## `GET /calls/org/{org_id}`

Bearer, must be a member of that organisation. Query parameters `limit` (default `50`, `1`–`500`) and `offset` (default `0`). Returns `CallLogListResponse`: `{calls: [...], limit, offset, total}`.

## `GET /calls/org/{org_id}/analytics`

Bearer, must be a member of that organisation — same check as the list route above, so a non-member gets `403` and an unknown organisation `404`. No query parameters: the figures are all-time over that organisation's call logs.

Returns `CallAnalyticsResponse`:

```json
{
  "calls_attempted": 412,
  "calls_connected": 337,
  "calls_failed": 75,
  "connection_rate": 81.8,
  "total_duration_seconds": 48213.0,
  "average_duration_seconds": 143.1,
  "trend_vs_last_week_pct": 2.4,
  "agent_performance": [
    { "agent_id": "…", "agent_name": "Support line", "call_count": 188 }
  ],
  "model_usage": {
    "stt": { "model": "saarika:v2", "provider": "sarvam", "call_count": 240 },
    "tts": { "model": "bulbul:v2", "provider": "sarvam", "call_count": 240 },
    "llm": { "model": "gpt-4o-mini", "provider": "openai", "call_count": 300 }
  }
}
```

Four things are not obvious from the field names:

* **"Connected" means `call_response == "answered"`, nothing else.** `total_duration_seconds` and `average_duration_seconds` are computed over connected calls only, not over all attempts — so the average is per *answered* call.
* **`trend_vs_last_week_pct` is `null`, not `0`, when the previous week had no attempts.** It is the difference between two connection *rates* in percentage points (this week minus last, rounded to 1 dp), not a change in call volume.
* **`agent_performance` is capped at the ten busiest agents.** It is a leaderboard, not a complete per-agent breakdown, and each row's `agent_id` and `agent_name` are whatever the call logs recorded at the time.
* **`model_usage` ranks each stage (`stt`/`tts`/`llm`) by call volume, not by agent count.** Each call is joined to its agent's *current* model config, grouped by `(model, provider)`, and only the single busiest model per stage is returned — not a full ranking. A stage is `null` if no call could be matched to a model (e.g. the agent was deleted). A model that used to be popular but was reconfigured away shows under its old name for calls made before the change and its new name for calls after, since the join uses the agent's config as it is *now*, not as it was at call time.

## `GET /calls/{call_id}`

Bearer. One `CallLogResponse`, active organisation only. Bot JWTs work here.

## Related

* [Endpoints cheatsheet](endpoints-cheatsheet) — every route on one page
* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
