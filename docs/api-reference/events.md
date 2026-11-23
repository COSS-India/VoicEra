---
title: Events (audit log)
description: Read and export the organisation's audit log.
---

`apps/api/app/routers/events.py`, prefix `/api/v1/events`. The audit log records access to call recordings and transcripts in an organisation, and exports of the log itself. Events are written by the API and are append-only; the API exposes no route to modify them.

## Access

Every route needs a Bearer token whose organisation the caller is currently an `admin` or `super_admin` of.

* The role is re-read from `Memberships` on every request, so a token issued before a demotion is refused.
* The bot service token is always refused, although it carries `role=admin`.
* Results are always scoped to the token's organisation.
* `503` means the role could not be verified because the database was unavailable. Retry the request.

## `GET /events`

One page of events, newest first.

| Query | Default | Rules |
| --- | --- | --- |
| `type` | all types | Repeatable. Must be a registered name from `GET /events/types` |
| `actor_id` | | Actor email. Up to 256 characters |
| `target_type`, `target_id` | | For example `call` and a call ID. Up to 256 characters each |
| `from` | 30 days before `to` | ISO 8601, inclusive. Not before 1970-01-01 |
| `to` | now | ISO 8601, inclusive. Later values are treated as now |
| `limit` | 50 | 1 to 200 |
| `cursor` | | `next_cursor` from the previous page |

The range from `from` to `to` can be at most 366 days.

```json
{
  "events": [
    {
      "id": "6743a1c8e4b0f1a2b3c4d5e6",
      "v": 1,
      "org_id": "org_123",
      "type": "call.transcript.downloaded",
      "ts": "2026-11-20T09:41:12.381Z",
      "source": "api",
      "actor": { "type": "user", "id": "jane@example.com", "role": "admin" },
      "target": { "type": "call", "id": "call_abc" },
      "outcome": "success",
      "context": { "ip": "203.0.113.7", "user_agent": "Mozilla/5.0 ..." },
      "data": { "object_key": "transcripts/call_abc.txt" }
    }
  ],
  "next_cursor": "6743a1c8e4b0f1a2b3c4d5e6"
}
```

`next_cursor` is `null` on the last page. Pages never overlap or skip events, even when many share a timestamp.

| Field | Meaning |
| --- | --- |
| `actor.type` | `user`, or `service` for the bot token |
| `actor.role` | The role in the caller's token at the time. It can lag a membership change by up to the token lifetime |
| `outcome` | `success`: the access was authorised and streaming began. `failure`: refused, with the reason in `data.reason` (`call_not_found`, `artifact_missing`, `invalid_artifact_url`, `storage_unavailable`) |
| `context` | Client IP and user agent. The IP is only the real client address when `FORWARDED_ALLOW_IPS` is configured. See [Security hardening](../guides/deployment/security-hardening) |
| `data` | Type-specific. For artifact access, `object_key`. Transcript downloads bundled in an OBD report ZIP also carry `campaign_id` |

Errors: `400` for an invalid range, an unknown type, or an invalid cursor. `422` for a `limit` or filter value outside its bounds.

## `GET /events/types`

The registered event types, as `name` and `description`.

| Type | Recorded when |
| --- | --- |
| `call.recording.viewed` / `.downloaded` | `GET /calls/{id}/recording` with `mode=view` or `mode=download` |
| `call.provider_recording.viewed` / `.downloaded` | `GET /calls/{id}/provider-recording` |
| `call.transcript.viewed` / `.downloaded` | `GET /calls/{id}/transcript`, and each transcript bundled into `GET /campaign/{id}/obd-report?format=zip` |
| `events.exported` | `GET /events/export`, with the filters in `data` |

Listing events with `GET /events` is not recorded; exports are.

## `GET /events/export`

The same filters as `GET /events`, streamed as CSV, newest first.

* Columns: `id`, `ts`, `type`, `outcome`, `actor_type`, `actor_id`, `actor_role`, `target_type`, `target_id`, `ip`, `user_agent`, `data`.
* Capped at `EVENTLOG_EXPORT_MAX_ROWS` (default 100,000). When rows were cut, the last line is `# truncated: export is limited to N rows`.
* Cells starting with `=`, `+`, `-`, `@`, tab, or carriage return are prefixed with `'`, so spreadsheets do not evaluate them.
* Each export is recorded as `events.exported` before the file streams.

## Retention

Events are kept for `EVENTLOG_RETENTION_DAYS`, default 365, and the API refuses to start with a lower value. The arq worker purges older events daily at 21:30 UTC.

## Related

* [Calls](calls)
* [Data model](../developer/reference/data-model)
* [Environment variables](../developer/reference/environment-variables)
* [Security hardening](../guides/deployment/security-hardening)
