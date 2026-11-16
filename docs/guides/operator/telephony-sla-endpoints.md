---
title: Telephony SLA HTTP endpoints
description: Provider API the VoicEra SLA telephony collector calls.
---

VoicEra reads telephony SLA numbers from the provider when `TELEPHONY_SLA_BASE_URL` and `TELEPHONY_SLA_TOKEN` are set on the API. Auth is `Authorization: Bearer <token>`. Times are ISO-8601 IST. Every call object includes `call_id` equal to the orchestration Call ID.

This page is the HTTP contract for [Telephony provider data requirements](telephony-provider-requirements). VoicEra only **reads** these routes in this pass.

## Endpoints the provider exposes

### `GET /v1/availability?from=&to=`

Minutes the WebSocket connection, number, or gateway was up and down.

Example response:

```json
{
  "availability_pct": 99.95,
  "peak_hours_availability_pct": 99.97,
  "websocket_up": true,
  "number_up": true,
  "gateway_up": true,
  "status": "up",
  "downtime_intervals": [
    {
      "start": "2026-11-01T02:00:00+05:30",
      "end": "2026-11-01T02:05:00+05:30",
      "component": "websocket"
    }
  ]
}
```

### `GET /v1/cdrs?from=&to=&cursor=`

Pages of CDRs, including calls that never connected.

Each row:

- `call_id` (matches orchestration Call ID)
- `direction`, `from`, `to`
- `assigned_number`, `flow`
- `dial_start_at`, `ring_or_answer_signal_at`, `answered_at`, `disconnect_at`
- `setup_result`, `failure_code`
- `disconnect_reason`
- `carrier_side_drop` (boolean: dropped by the carrier or before audio reached orchestration)

### `GET /v1/media?from=&to=`

Per `call_id`, measured on the WebSocket audio stream:

- `one_way_media_delay_ms`
- `jitter_ms`
- `packet_loss_pct`
- `mos`

A period summary may also be returned under `summary` with the same fields plus:

- `post_dial_delay_p95_s`
- `connection_time_p95_ms`
- `call_setup_success_pct`
- `carrier_side_call_drops_pct`

### `GET /v1/capacity`

```json
{
  "reserved_connections": 900,
  "burst_headroom_pct": 15,
  "connections_in_use": 61,
  "rejected_under_875": 0,
  "over_limit_attempts": 3,
  "over_limit_clear_busy": 3
}
```

### `GET /v1/incidents?from=&to=`

Provider incidents with `priority`, `started_at`, `notified_at`, `restored_at`, `preliminary_rca_at`, `final_rca_at`.

## Webhook the provider calls later

`POST /v1/webhooks/capacity` is what the provider calls on VoicEra when connections cross 80% or 90%. Body:

```json
{
  "level": "80",
  "connections_in_use": 700,
  "reserved": 875,
  "at": "2026-11-16T14:00:00+05:30"
}
```

VoicEra does not receive this webhook in the current API pass. The route is documented so the provider can implement the sender.

## VoicEra collector

`GET /api/v1/sla/telephony` calls the provider routes above when configured. When `TELEPHONY_SLA_BASE_URL` or `TELEPHONY_SLA_TOKEN` is missing, every telephony metric is returned with `actual: null`, `status: no_data`, `source: telephony_unconfigured`, and `operating_status: unknown`.
