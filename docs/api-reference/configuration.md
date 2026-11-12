---
title: Configuration catalogs
description: Discover which providers exist and what each one accepts.
---

## Configuration

`apps/api/app/routers/configuration.py`, prefix `/api/v1/configuration`. The self-describing provider catalogue. Everything here is generated from the registry at runtime, so a newly added provider appears without a code change here. See [Provider registry](../developer/reference/provider-registry).

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/configuration/stt` | Bearer | Registered STT providers. Optional `languages` query. |
| GET | `/configuration/tts` | Bearer | Registered TTS providers. Optional `languages` query. |
| GET | `/configuration/llm` | Bearer | Registered LLM providers. |
| GET | `/configuration/telephony` | Bearer | Registered telephony providers. |
| GET | `/configuration/stt/setting/{provider}` | Bearer | Setting schema for one STT provider. Optional `languages`. |
| GET | `/configuration/tts/setting/{provider}` | Bearer | Setting schema for one TTS provider. Optional `languages`. |
| GET | `/configuration/llm/setting/{provider}` | Bearer | Setting schema for one LLM provider. |
| GET | `/configuration/telephony/setting/{provider}` | Bearer | Setting schema for one telephony provider. |

`languages` is a comma-separated list of canonical language ids and acts as an **AND** filter: `?languages=en,hi` returns only providers supporting both.

Every list and setting response includes `authenticated`: `true` when the caller's organisation has stored credentials for that provider (same source as `GET /auth/configured`), otherwise `false`. List entries stay identity-only otherwise (`provider`, `name`, `provider_type`, `authenticated`).

The `setting` routes return the field catalogue for that provider — enough to render a configuration form and to know which keys `config.models.{stt,tts,llm}_config` will accept. An unknown provider returns `404`; a malformed request returns `400`.

#### STT / TTS setting payload

`GET /configuration/{stt|tts}/setting/{provider}` includes a top-level `capabilities` map (secrets stay on auth routes, not here):

```text
capabilities:
  model_id → {
    languages: { canonical_id: vendor_wire_code, ... },
    settings: {
      canonical_id → setting_name → {
        default?, options?, minimum?, maximum?,
        input_type?, allow_custom_input?, description?
      }
    }
  }
```

- **`languages` and `settings` keys are canonical ids** from `apps/providers/languages.py` (`hi`, `en`, `multi`, …) — not vendor-only codes like `hi-IN` as map keys.
- `languages` values are the vendor wire codes (for translating agent config back to the provider API).
- With `?languages=`, `capabilities` keeps only models that support **all** selected ids — the same set as `fields.model.examples`. If no model matches, `capabilities` is `{}`.
- List routes (`GET /configuration/stt` etc.) stay identity-only (`provider`, `name`, `provider_type`, `authenticated`); they do not include `capabilities`.

## Languages

`apps/api/app/routers/languages.py`.

### `GET /languages`

Bearer. Returns the canonical language id → label map that the agent builder's picker uses:

```json
{ "languages": { "en": "English", "hi": "Hindi" } }
```

These ids are what `config.language.primary` accepts. Which of them a given provider actually supports is a separate question — filter with `GET /configuration/stt?languages=`.

## Voice preview

`apps/api/app/routers/tts_preview.py`, prefix `/api/v1/tts`. Speaks text with an **unsaved** TTS config, so a voice can be heard before the agent exists. Synthesis calls the vendor's REST API directly through the provider's preview adapter (`apps/providers/preview.py`) — never through `apps/runtime` or Pipecat — so previews cannot compete with live calls.

### `POST /tts/preview`

Bearer, with an active organisation.

```json
{
  "tts_config": { "provider": "sarvam", "model": "bulbul:v3", "voice": "shubh" },
  "language": "hi",
  "text": "Namaste {{customer_name}}, thanks for calling."
}
```

`tts_config` takes the same non-secret shape as `config.models.tts_config`; the organisation's stored credentials for that provider are merged in server-side. `language` is a canonical id from `GET /languages`, and it overrides any `language` inside `tts_config`. `{{placeholders}}` are stripped from `text` before synthesis.

Returns the clip as `audio/wav` bytes, not JSON.

Errors carry a machine-readable code, `{"detail": {"code": "…", "message": "…"}}`, because several reasons share a status:

| Status | `code` | When |
| --- | --- | --- |
| `400` | `no_active_org` | The token has no active organisation. |
| `400` | `empty_text` | `text` is empty once placeholders are stripped. |
| `409` | `not_configured` | The organisation has no stored credentials for that provider. |
| `413` | `oversized` | `text`, once placeholders are stripped, is longer than `TTS_PREVIEW_MAX_CHARS` (default `300`). |
| `422` | `invalid_config` | `tts_config` fails provider validation. |
| `422` | `unsupported_voice` | The provider has no preview adapter, or the voice is not offered for `language`. |
| `429` | `rate_limited` | Over `TTS_PREVIEW_RATE_LIMIT_PER_MINUTE` (default `20`) for the organisation. Carries `Retry-After`. |
| `502` | `upstream` | The vendor call failed. The message is deliberately generic; the detail is in the API log. |
| `504` | `timeout` | The vendor took longer than `TTS_PREVIEW_TIMEOUT_S` (default `15`). |

Three things are not obvious:

* **Clips are cached per organisation.** The key is the secret-free config plus the stripped text, stored in the MinIO bucket `TTS_PREVIEW_BUCKET` (default `voicera-tts-preview`) as `{org_id}/{sha256}.wav`, with a 7-day expiry. A cache hit is checked first, so it costs no vendor call, does not count against the rate limit, and still plays after the provider's credentials are removed.
* **The rate limit is a fixed one-minute window per organisation, held in Redis.** Every uncached request that passes validation counts, including one that then fails with `409`; a `400`, `413`, or `422` from validation never does. If Redis is unreachable the limiter fails open — previews keep working, unlimited.
* **Every TTS provider except `lmnt` has a preview adapter.** For `lmnt`, `POST /tts/preview` returns `422 unsupported_voice`.

### `GET /tts/preview/limits`

Bearer. The limits the dashboard checks before calling `POST /tts/preview`, so the server stays the source of truth:

```json
{ "max_chars": 300 }
```

## Related

* [Endpoints cheatsheet](endpoints-cheatsheet) — every route on one page
* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
