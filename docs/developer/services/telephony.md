---
title: Telephony (apps/telephony)
description: The telephony package — clients, XML, serializers, and webhooks.
---

`apps/telephony` holds provider-agnostic HTTP clients and helpers for Vobiz, Plivo, Vodafone Idea, and Go2Market. Like [`apps/providers`](providers) it is a library, not a container: it is copied into both the `api` and `runtime` images. The API uses it to provision applications and phone numbers; the runtime uses it to build answer XML (where applicable), parse webhooks, and serialize audio frames.

<Note>
This page covers the package layout and public API. The conceptual model — applications, numbers, inbound versus outbound, what each provider owns — is in [Telephony model](../../guides/concepts/telephony-model).
</Note>

Credentials and `base_url` are always injected by the caller. The package never reads `ProviderAuth`, FerretDB, or environment variables for auth.

## Public API

```python
from apps.telephony import VobizClient, PlivoClient, ViClient, Go2MarketClient

vobiz = VobizClient(
    auth_id="...",
    auth_token="...",
    base_url="https://api.vobiz.ai/api/v1",
)
plivo = PlivoClient(
    auth_id="...",
    auth_token="...",
    base_url="https://api.plivo.com/v1",
)
# ViClient / Go2MarketClient take OBD credentials from Integrations (see provider docs).
```

The catalog follows the same pattern as `apps.providers.schema`:

```python
from apps.telephony import Kind, provider_schemas, configuration_telephony, create_client
from apps.telephony.providers.vobiz.config import VobizConfig

schemas = provider_schemas(Kind.TELEPHONY)
# schemas["vobiz"]["secrets"] == ["auth_id", "auth_token"]
# schemas["vobiz"]["fields"]["auth_id"]["integration_model"] == "VobizAuthId"

defaults = configuration_telephony()
# {"telephony": {...}, "default_providers": {"telephony": "vobiz"}}

client = create_client(VobizConfig(auth_id="...", auth_token="..."))
```

`apps/telephony/__init__.py` calls `load_providers()` at import, so vendor configs are registered as soon as the package is imported. Frame serializers are the exception — they need Pipecat and are loaded separately, on demand.

Dump the catalog from a shell:

```bash
python3 apps/telephony/scripts/print_schemas.py
```

## Method map

| Area | Methods |
|------|---------|
| Application | `create_application`, `delete_application`, `update_application_name`, `link_number`, `unlink_number`, `list_numbers` |
| Outbound | `client.initiate_call(...)` or `initiate_outbound(provider, ...)` |
| Recording | `start_call_recording`, `fetch_recording_metadata`, `download_recording`, `wait_and_download_recording` (+ Plivo `list_recordings_for_call`) |
| Answer XML | `build_answer_stream_xml(provider, websocket_url, sample_rate=...)` |
| Frame serializers | `create_frame_serializer(provider, stream_sid=..., call_sid=..., sample_rate=...)` |
| Schemas | `apps.telephony.providers.{vobiz,plivo,vi,go2market}.schemas` |

Application and outbound methods return `{status, message, ...}` dicts built by the `ApiResult` dataclass in `base.py`, where `status` is `"success"` or `"fail"`. Recording helpers return ids or bytes, or `None`. `list_recordings_for_call` exists on Plivo only.

### Outbound call

The caller resolves credentials and builds the answer and hangup URLs; the library only makes the HTTP request:

```python
from apps.telephony import VobizClient, initiate_outbound

# Via client
client = VobizClient(auth_id, auth_token, base_url)
result = await client.initiate_call(
    from_number="+1555...",
    to_number="+1555...",
    answer_url="https://voice.example.com/answer?agent_id=...&org_id=...",
)

# Or dispatch by provider name (Plivo also takes hangup_url)
result = await initiate_outbound(
    "plivo",
    auth_id=...,
    auth_token=...,
    base_url=...,
    from_number=...,
    to_number=...,
    answer_url=...,
    hangup_url=...,
)
```

`initiate_outbound()` builds the typed config, creates the client, and calls `initiate_call()`. The Vobiz payload carries no hangup fields; Plivo includes `hangup_url` and `hangup_method` when they are provided.

### Answer XML

The runtime keeps a single `/answer` route and dispatches on the agent's provider:

```python
from apps.telephony import build_answer_stream_xml

xml = build_answer_stream_xml(
    provider,                 # "vobiz" | "plivo" (VI / Go2Market use stubs / no Stream XML)
    websocket_url,
    sample_rate=16000,
)
```

`sample_rate` defaults to `8000` and selects the `contentType`. The XML format is identical for Vobiz and Plivo today, but each provider owns its own `xml.py` so they can diverge later. VI and Go2Market do not drive live media through this XML — see [Go To Market](go2market) and the [VI exception](../guides/adding-a-telephony-provider#vodafone-idea-vi-exception).

## Per-provider layout

Every provider under `providers/<name>/` follows the same contract:

| File | Role |
| --- | --- |
| `config.py` | Auth / Settings / Config Pydantic layers, registered with `@register_telephony` |
| `service.py` | `@register_client` and `@register_answer_xml` creators |
| `client.py` | HTTP client — auth headers and base URL |
| `application.py` | Application CRUD and the outbound Call API |
| `recording.py` | Native call recording |
| `xml.py` | The provider's full answer-stream XML format |
| `serializers.py` | The Pipecat frame serializer class |
| `serializer_service.py` | `@register_frame_serializer` creator, loaded lazily |
| `schemas.py` | Pydantic request and response shapes for that vendor's API |

`registry.py` keeps four maps — `TELEPHONY_CONFIGS`, `CLIENT_CREATORS`, `ANSWER_XML_BUILDERS`, and `FRAME_SERIALIZER_FACTORIES` — and rejects a duplicate registration for a provider id with a `ValueError`. Provider ids are normalised to lower case, so lookups are case-insensitive.

Do not add provider `if`/`elif` chains to the package-root `xml.py`, `calls.py`, or `serializers.py`. Those three modules are thin dispatchers over the registry, and that is all they should be. To add a vendor, follow [Adding a telephony provider](../guides/adding-a-telephony-provider).

## Frame serializers

Serializers require Pipecat, so they live behind a second, lazy discovery pass and are never re-exported from `apps.telephony` — the API can use Application and Recording without Pipecat installed. The runtime imports the parent factory:

```python
from apps.telephony.serializers import create_frame_serializer

serializer = create_frame_serializer(
    "vobiz",                  # or "plivo" | "vi" | "go2market"
    stream_sid=stream_sid,
    call_sid=call_sid,
    sample_rate=8000,
)
```

An unregistered provider raises `ValueError`. Per-provider classes are importable directly when you need the type:

```python
from apps.telephony.providers.vobiz.serializers import VobizFrameSerializer
from apps.telephony.providers.plivo.serializers import PlivoFrameSerializer
from apps.telephony.providers.vi.serializers import ViFrameSerializer
from apps.telephony.providers.go2market.serializers import Go2MarketFrameSerializer
```

## Webhooks

`webhooks.py` normalises what the two providers send, so the runtime's `/answer` route never branches on vendor field names.

| Helper | What it does |
| --- | --- |
| `decode_webhook_body(raw)` | Parses the body as JSON or `x-www-form-urlencoded`. `request.form()` reads only form types, so a JSON `From` / `To` / `CallUUID` would otherwise be dropped. |
| `merge_webhook_payload(form, query)` | Merges query parameters into the form data — Vobiz may send `CallUUID` on the URL. Form values win. |
| `parse_webhook_form(form)` | Returns a frozen `TelephonyWebhookEvent` with `event`, `from_number`, `to_number`, `direction`, `provider_call_sid`, `hangup_cause`, and `call_status`. |
| `resolve_provider_call_sid(payload)` | Tries ten known key paths — `CallUUID`, `call_uuid`, `call_id`, `callId`, `callSid`, `CallSid`, `request_uuid`, and nested `start.*` variants. |
| `parse_stream_start(start_info)` | Pulls the call SID and numbers out of a WebSocket `start` object, defaulting the numbers to `"unknown"`. |
| `is_hangup_event(event)` | True for `hangup`, `hangupcomplete`, or `callhangup`. |
| `map_hangup_call_response(status, cause)` | Maps a provider hangup cause to a VoicEra call response. |

Missing numbers default to `"unknown"` rather than raising, and `direction` defaults to `"inbound"`.

## Schemas

`schema.py` mirrors `apps.providers.schema`. `provider_schemas(Kind.TELEPHONY)` returns a readable catalog per provider with `secrets`, `required`, and `fields`; `configuration_telephony()` wraps it with `default_providers`, where the telephony default is `vobiz`. Field extras carried through to the catalog are `secret`, `examples`, `multiline`, `docs_url`, and `integration_model`. `kind`, `provider`, and `name` are omitted from `fields`.

This is what `GET /api/v1/configuration/telephony` returns.

## Out of scope

The package deliberately does not do these things. Its callers do.

* Phone attach and detach against FerretDB — that is `apps/api`.
* MinIO storage and recording submission — that is `apps/runtime`.
* The FastAPI `/answer` route and the WebSocket endpoint — the [runtime](runtime) owns those and calls the XML helper.
* Agent config and credential lookup — the caller injects `auth_id`, `auth_token`, and `base_url`.

<Note>
`apps/telephony/README.md` in the repository is the package's own reference, kept in step with this page.
</Note>

## Related

* [Telephony model](../../guides/concepts/telephony-model) — applications, numbers, and call direction
* [Go To Market](go2market) — OBD, DID-WebSocket, µ-law streaming
* [Telephony agents](../clients/telephony) — connecting a number to an agent
* [Adding a telephony provider](../guides/adding-a-telephony-provider)
* [Telephony troubleshooting](../../guides/troubleshooting/telephony)
