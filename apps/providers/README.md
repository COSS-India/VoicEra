# Providers

> [![Vendors](https://img.shields.io/badge/vendors-22%20cloud%20%2B%201%20adapter-brightgreen.svg)](#layout)
[![Registry](https://img.shields.io/badge/pattern-decorator%20registry-blue.svg)](#adding-a-provider)

Adding a vendor never means editing a central `if/elif` — registration is a decorator, and the schema dump follows automatically.

Pydantic configs and a factory that build Pipecat (and first-party) STT, TTS, and LLM services.

## Public API

```python
from apps.providers import (
    AgentConfig,
    Kind,
    create_stt_service,
    create_tts_service,
    create_llm_service,
)
from apps.providers.languages import LANGUAGES, label

agent = AgentConfig.model_validate({
    "stt_config": {"provider": "deepgram", "api_key": "...", "model": "nova-3"},
    "tts_config": {"provider": "openai", "api_key": "..."},
    "llm_config": {"provider": "openai", "api_key": "...", "model": "gpt-4.1-mini"},
})

stt = create_stt_service(agent)
tts = create_tts_service(agent)
llm = create_llm_service(agent)
```

`cloud/factory.py` is a compatibility re-export of the same symbols. New code should import from `apps.providers` or `apps.providers.factory`.

## Schema dump for the API

Provider availability, field requirements, secrets, suggested models, and
supported languages live on the config classes. Dump a **readable catalog**
(not raw JSON Schema) — do not maintain a second list in the router or UI.

```python
from apps.providers import Kind, provider_schemas, configuration_defaults

openai = provider_schemas(Kind.LLM)["openai"]
# {
#   "provider": "openai",               # from provider: Literal["openai"] = "openai"
#   "name": "OpenAI",                   # UI display name from config.name
#   "provider_type": "cloud",           # cloud | adapter | local
#   "description": "...",
#   "required": ["api_key"],
#   "secrets": ["api_key"],             # auth fields at a glance
#   "fields": {
#     "api_key": {"type": "...", "secret": true},
#     "model": {"type": "string", "examples": [...], "input_mode": "both"},
#     "base_url": {"type": "string", "input_mode": "input"},
#   },
# }

deepgram_lang = provider_schemas(Kind.STT)["deepgram"]["fields"]["language"]
# deepgram_lang["examples"]         → flat canonical ids
# deepgram_lang["model_options"]    → model → [canonical ids]
# deepgram_lang["language_codes"]   → model → {canonical: vendor_code}
# deepgram_lang["input_mode"]       → "options" | "input" | "both"

defaults = configuration_defaults()
# {
#   "stt": {...}, "tts": {...}, "llm": {...},
#   "default_providers": {...},
#   "languages": {"hi": "Hindi", "en": "English", ...},
# }
```

Catalogs are derived from the discriminated unions in `factory.py` (not raw
JSON Schema — no `$defs` / `$ref` / `anyOf`).

- **`provider_type`** comes from the config module path (`cloud/` / `adapters/` / `local/`).
- **`input_mode`** is derived from Field `examples` / `model_options` + `allow_custom_input`
  (`options` = list only, `input` = free text, `both` = select or type). Secrets have no
  `input_mode`. Language extras come from each vendor’s `STT_CAPABILITIES` /
  `TTS_CAPABILITIES` via `languages_map()` + `language_schema_extra()`.

## Layout

| Path | Role |
|------|------|
| `base.py` | Shared `Kind` / `ProviderType` enums and Auth/Settings/Config bases |
| `registry.py` | `@register_*` maps, `load_providers()`, creator helpers (`api_key`, `llm_settings`) |
| `factory.py` | Discriminated unions from registry + thin `create_*` dispatch |
| `schema.py` | `provider_schemas` / `configuration_defaults` readable catalog dump |
| `languages.py` | Canonical language ids → labels; `language_schema_extra()` |
| `capabilities.py` | `model_ids` / `languages_map` / `settings_tree` / `expand_settings` |
| `scoped_settings.py` | Normalize + `resolve_settings` for dumped trees |
| `cloud/<vendor>/` | Pipecat-backed vendors (`catalog`, `config`, `service`) → `provider_type=cloud` |
| `adapters/<vendor>/` | First-party services (`service.py` + optional `tts.py`) → `provider_type=adapter` |
| `local/<vendor>/` | Reserved for self-hosted providers → `provider_type=local` |

Bhashini in this package is **TTS only** (NVCF gRPC). Dhruva / Bhashini STT is not here yet.

## Auth vs Settings vs Config

Each vendor `config.py` stacks three layers:

1. **Auth** — credentials (`api_key`, `auth_token`, …). Secrets use `json_schema_extra={"secret": True}`.
2. **Settings** — vendor knobs (`voice`, `speed`, `base_url`, `grpc_url`, …).
3. **Config** — Auth + Settings + `Base*Config` (`provider`, `model`, `language`).

Credentials do not live on the bases. Endpoints and hosts belong on Settings, not Auth.

## Languages + capabilities (STT / TTS)

Canonical ids and labels live in root `languages.py` (`hi`, `en`, `en-US`, `multi`, …).
Each STT/TTS vendor declares **one** map in `catalog.py` — no per-vendor `languages.py`:

```python
STT_CAPABILITIES = {
    "u3-rt-pro": {
        "languages": {"en": "en"},           # vendor_code → canonical_id
        "settings": {"en": {}},              # vendor_code only — no "*"
    },
}
```

Shared knobs across languages: use `expand_settings(languages, meta)` when building
the constant (result still has one block per vendor code).

Wire in `config.py`:

```python
from ...capabilities import languages_map, model_ids, settings_tree
from ...languages import language_schema_extra
from .catalog import STT_CAPABILITIES

_STT_MODELS = model_ids(STT_CAPABILITIES)

class AcmeSTTConfig(...):
    settings_by_model_language: ClassVar[dict] = settings_tree(STT_CAPABILITIES)

    model: str = Field(default=_STT_MODELS[0], ...)
    language: str = Field(
        ...,
        json_schema_extra=language_schema_extra(languages_map(STT_CAPABILITIES)),
    )
```

- Do **not** define `DEFAULT_STT_MODEL` / `DEFAULT_TTS_MODEL` in catalog; use
  `model_ids(CAPABILITIES)[0]` for Field defaults.
- `settings_tree()` rekeys vendor → **canonical** for config ClassVars.
  Schema dumps top-level ``capabilities`` as
  ``{model: {languages: {canonical: vendor}, settings: {canonical: …}}}``.
  `resolve_settings(tree, model, language)` takes canonical ids.
- Setting names must match Settings fields. Only advertise knobs `service.py` passes
  through. Keep infra URLs as catalog constants, not Settings/tree entries.
- Global labels ship once on `configuration_defaults()["languages"]`.
- Vendor language **defaults** may differ (`en`, `en-US`, `hi`, `multi`).

## Adding a provider

1. Add `cloud/<name>/`, `adapters/<name>/`, or `local/<name>/` with `catalog.py`,
   `config.py`, and `service.py` (STT/TTS: put `*_CAPABILITIES` in catalog; LLM-only
   vendors need no language map).
2. Put credentials on Auth, knobs on Settings, and on Config set
   `name: str = "Display Name"` (UI label) plus `provider: Literal["…"] = "…"`.
3. On STT/TTS `language` fields, use
   `language_schema_extra(languages_map(CAPABILITIES))`.
4. For selectable fields, set `examples` and optionally `allow_custom_input=True`
   (catalog becomes `input_mode` `both` vs `options`).
5. Set `settings_by_model_language: ClassVar = settings_tree(CAPABILITIES)` on STT/TTS
   Config classes.
6. In `service.py`, implement `@register_stt` / `@register_tts` / `@register_llm`
   creators. Import Pipecat **inside** the creator so missing extras do not break
   package import.
7. Do **not** edit a central if/elif in `factory.py` — registration + `load_providers()`
   pick up the new module. Schema dump follows automatically.

Adapters that implement a Pipecat `TTSService` / `STTService` subclass live next to their config (see `adapters/bhashini/tts.py`).

## Dependencies

Core: `pydantic`, `loguru`, `pipecat-ai` (plus per-vendor Pipecat extras).

Bhashini adapter extra: `grpcio`, `protobuf`, `numpy`.

---

Full documentation: [Provider registry](../../docs/guides/concepts/provider-registry.md) · [Adding an AI provider](../../docs/developer/guides/adding-a-provider.md) · [Providers package](../../docs/developer/services/providers.md)
