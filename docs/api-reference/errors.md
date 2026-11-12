---
title: Errors
description: Status codes, error shapes, and what each one means.
---

Every handled error is a FastAPI `HTTPException`, which serialises as:

```json
{ "detail": "Organisation not found: org_abc123" }
```

Voice preview errors put an object in `detail` instead, so a client can tell apart reasons that share a status:

```json
{ "detail": { "code": "not_configured", "message": "Provider 'sarvam' is not configured for this organisation" } }
```

The codes are listed under [`POST /tts/preview`](configuration#post-ttspreview).

A validation failure is different. FastAPI returns `422` with a list:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "config", "language", "primary"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

`loc` walks from the request part inwards, so it tells you exactly which nested field failed. Agent config validation failures also arrive as `422`, but with a single string in `detail` rather than a list, because they are raised by hand.

## Status codes

| Code | Meaning | Common cause |
| --- | --- | --- |
| `400` | Bad request | No active organisation in the token; a websocket agent asked for `/answer`. |
| `401` | Unauthenticated | Missing, malformed, or expired token; wrong `X-API-Key`. |
| `403` | Wrong role or wrong organisation | Authenticated, but the role or membership does not permit it. |
| `404` | Not found | The id does not exist, or exists in another organisation. |
| `409` | Conflict | Duplicate signup email; a campaign state transition that is not allowed; deleting a phone number still attached to an agent; no LLM provider configured for transcript translation; voice preview for a provider with no stored credentials. |
| `413` | Too large | Voice preview text over `TTS_PREVIEW_MAX_CHARS`; a transcript too long to translate in one request. |
| `422` | Validation failed | A field is missing, out of range, or the wrong type. |
| `423` | Locked | The same transcript is already being translated into that language. Retry shortly. |
| `429` | Rate limited | Voice preview or uncached transcript translation over its per-organisation, per-minute limit. Honour `Retry-After`. |
| `500` | Server error | `INTERNAL_API_KEY` unset; an unhandled provider failure; a stored transcript that is not valid UTF-8. |
| `502` | Upstream failed | The voice or LLM provider call failed, or the translation came back with a different line structure. |
| `503` | Unavailable | A MinIO error other than a missing object; Redis unreachable for the translation lock or rate limit; every translation slot busy for 30 seconds. |
| `504` | Upstream timed out | A voice preview took longer than `TTS_PREVIEW_TIMEOUT_S`. |

<Note>
A `404` on a resource you know exists usually means your token's active organisation is not the one that owns it. Swap with `POST /api/v1/users/switch-organisation` and retry.
</Note>

## Related

* [Authentication](authentication)
* [Troubleshooting](../guides/troubleshooting/index)
