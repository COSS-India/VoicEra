---
title: Post-call webhooks
description: One signed POST per finished call to an agent's webhook URL.
---

`apps/api/app/services/call_webhook_service.py`. Turn it on per agent with `config.webhook`; VoicEra then sends one `call.ended` event for every call on that agent that ends, answered or not.

## Turn it on

1. Set the URL on the agent (`PATCH /api/v1/agents/{agent_id}`):

   ```json
   { "config": { "webhook": { "enabled": true, "url": "https://receiver.example.com/voicera" } } }
   ```

   The URL must be `https://` unless `CALL_WEBHOOK_ALLOW_HTTP=true` (local development only). A `PATCH` whose `config` leaves out `webhook` keeps the current setting.

2. Create the signing secret (admin or super_admin):

   ```bash
   curl -X POST http://localhost:8000/api/v1/agents/AGENT_ID/webhook/secret \
     -H "Authorization: Bearer YOUR_JWT"
   ```

   Returns `{"agent_id": "…", "secret": "whsec_…"}` with `201`. The secret is stored encrypted and is shown only in this response; calling it again rotates the secret and the old one stops working at once. Deliveries made while no secret exists fail and are retried.

## When it fires

A delivery is queued the first time a call log reaches `status: "completed"` or `status: "failed"`, whichever path writes it (runtime `PATCH`, provider hangup webhook, or a failed dial). It is sent after `CALL_WEBHOOK_SETTLE_SECONDS` (default 20) so the transcript and recording patches that land after the hangup are included. Each call gets at most one delivery row, so patching a finished call again never sends a second event; use redeliver for that.

The `arq-worker` service sends due deliveries every 10 seconds (`dispatch_call_webhooks` cron).

## Request

`POST` to the agent's URL, JSON body:

```json
{
  "event": "call.ended",
  "delivery_id": "3f6c…",
  "attempt": 1,
  "sent_at": "2026-11-13T10:03:21.512+00:00",
  "data": {
    "call_id": "3f6c…",
    "org_id": "org_abc123",
    "agent_id": "…",
    "agent_name": "KKB Hubli",
    "call_type": "outbound",
    "status": "completed",
    "call_response": "answered",
    "from_number": "+918000000000",
    "to_number": "+919999999999",
    "telephony_provider": "vi",
    "provider_call_sid": "…",
    "custom_variables": { "participant_id": "P-42", "location": "Hubli" },
    "campaign_id": "…",
    "campaign_name": "KKB Hubli wk46",
    "queued_run_id": "…",
    "start_time_utc": "2026-11-13T10:00:00+00:00",
    "end_time_utc": "2026-11-13T10:03:00+00:00",
    "duration": 180.0,
    "error_message": null,
    "created_at": "2026-11-13T09:59:58+00:00",
    "artifacts": {
      "transcript_path": "/api/v1/calls/3f6c…/transcript",
      "recording_path": "/api/v1/calls/3f6c…/recording",
      "metrics_path": "/api/v1/calls/3f6c…/metrics"
    }
  }
}
```

`data` is the call log minus internal storage URLs. Artifacts are API paths on the same VoicEra API; fetch them with your token. `delivery_id` is the `call_id`; dedupe on it, because a retry or a manual redeliver sends the same call again.

Headers:

| Header | Value |
| --- | --- |
| `X-VoicEra-Event` | `call.ended` |
| `X-VoicEra-Delivery` | The `call_id` |
| `X-VoicEra-Attempt` | 1-based attempt number |
| `X-VoicEra-Timestamp` | Unix seconds when signed |
| `X-VoicEra-Signature` | `v1=<hex>` |

## Verify the signature

`hex = HMAC-SHA256(secret, "{X-VoicEra-Timestamp}.{raw request body}")`. Compute it over the raw bytes before parsing JSON, compare in constant time, and reject timestamps more than 5 minutes old.

```python
import hashlib, hmac, time

def verify(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    expected = "v1=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

## Retries

Any `2xx` within `CALL_WEBHOOK_TIMEOUT_SECONDS` (default 10) counts as delivered. Anything else, or a network error, is retried after 30 s, doubling each time up to 1 hour, for `CALL_WEBHOOK_MAX_ATTEMPTS` (default 8, about 2 hours in all). After that the delivery is `failed`. Redirects are not followed. If the agent's webhook is switched off before a retry, the delivery stops as `failed`.

## Status and redeliver

### `GET /calls/{call_id}/webhook`

Bearer. The delivery for one call: `state` (`pending`, `in_flight`, `delivered`, `failed`), `attempts`, `last_status_code`, `last_error`, `next_attempt_at`, `last_attempt_at`, `delivered_at`. `404` when the call has no delivery.

### `POST /calls/{call_id}/webhook/redeliver`

Bearer. `202`. Queues the call to be sent now and resets `attempts`. Also works for an ended call that never had a delivery (for example, one that ended before the webhook was turned on). `409` when the call has not ended or its agent has no enabled webhook.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `CALL_WEBHOOK_SETTLE_SECONDS` | `20` | Wait after a call ends before the first try |
| `CALL_WEBHOOK_TIMEOUT_SECONDS` | `10` | HTTP timeout per try |
| `CALL_WEBHOOK_MAX_ATTEMPTS` | `8` | Tries before `failed` |
| `CALL_WEBHOOK_BACKOFF_BASE_SECONDS` | `30` | First retry delay, doubled each try |
| `CALL_WEBHOOK_BACKOFF_MAX_SECONDS` | `3600` | Longest retry delay |
| `CALL_WEBHOOK_LEASE_SECONDS` | `120` | How long a worker holds a claimed delivery |
| `CALL_WEBHOOK_DISPATCH_BATCH` | `50` | Deliveries per dispatcher run |
| `CALL_WEBHOOK_ALLOW_HTTP` | `false` | Allow `http://` URLs (development only) |

The secret is encrypted with `PROVIDER_AUTH_ENCRYPTION_KEY`, which must be set.

## Related

* [Agents](agents) — `config.webhook`
* [Calls](calls) — the call log the event carries
