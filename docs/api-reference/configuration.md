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

## Related

* [Endpoints cheatsheet](endpoints-cheatsheet) — every route on one page
* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
