# Telephony

> Provider-agnostic clients for Vobiz and Plivo, shared by `apps/api` and `apps/runtime`.

[![Providers](https://img.shields.io/badge/providers-Vobiz%20%C2%B7%20Plivo-brightgreen.svg)](#provider-catalog-for-appsapi--ui)
[![Registry](https://img.shields.io/badge/pattern-decorator%20registry-blue.svg)](#provider-catalog-for-appsapi--ui)

One `/answer` webhook serves every carrier. Per-provider modules own the differences.

## Install / import

Ensure `voicera/` is on `PYTHONPATH`:

```python
from apps.telephony import VobizClient, PlivoClient

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
```

Credentials and `base_url` are always injected. This package does **not** read
org `ProviderAuth`, the database, or environment variables for auth.

## Provider catalog (for `apps/api` / UI)

Same pattern as `apps.providers.schema`:

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

Per-provider configs live in `providers/{name}/config.py` (Auth / Settings / Config).
Service creators (client, answer XML) register in `providers/{name}/service.py`
via `@register_client` and `@register_answer_xml`. Frame serializers register
in optional `providers/{name}/serializer_service.py` (requires pipecat) and are
loaded lazily by the voice runtime only. Do not add provider if/elif chains to
the package-root `xml.py`, `calls.py`, or `serializers.py` facades.

| Area | Methods |
|------|---------|
| Application | `create_application`, `delete_application`, `update_application_name`, `link_number`, `unlink_number`, `list_numbers` |
| Outbound | `client.initiate_call(...)` or `initiate_outbound(provider, ...)` |
| Recording | `start_call_recording`, `fetch_recording_metadata`, `download_recording`, `wait_and_download_recording` (+ Plivo `list_recordings_for_call`) |
| Answer XML | `build_answer_stream_xml(provider, websocket_url, sample_rate=...)` |
| Frame serializers | `create_frame_serializer(provider, stream_sid=..., call_sid=..., sample_rate=...)` |
| Schemas | `apps.telephony.providers.vobiz.schemas` / `...plivo.schemas` |

Application / outbound methods return `{status, message, ...}` dicts. Recording
helpers return ids/bytes or `None`.

## Outbound call

Callers resolve credentials from `ProviderAuth` and build answer/hangup URLs; the library only
hits `POST .../Account/{auth}/Call/`:

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

Vobiz Call payload does not include hangup fields. Plivo includes `hangup_url` /
`hangup_method` when provided.

## Answer XML (one `/answer` route)

The runtime keeps a single `/answer` webhook and dispatches by agent provider:

```python
from apps.telephony import build_answer_stream_xml

xml = build_answer_stream_xml(
    provider,                 # "vobiz" | "plivo"
    websocket_url,
    sample_rate=16000,
)
```

XML format is the same for Vobiz and Plivo today. Per-provider files under
`providers/{vobiz,plivo}/xml.py` own the format so they can diverge later.
Callers should use the parent `build_answer_stream_xml` only.

## Serializers (optional, needs pipecat)

The runtime should use the parent factory:

```python
from apps.telephony.serializers import create_frame_serializer

serializer = create_frame_serializer(
    "vobiz",                  # or "plivo"
    stream_sid="stream-1",
    call_sid="call-1",
    sample_rate=8000,
)
```

Per-provider classes are also available directly:

```python
from apps.telephony.providers.vobiz.serializers import VobizFrameSerializer
from apps.telephony.providers.plivo.serializers import PlivoFrameSerializer
```

Not re-exported from `apps.telephony` so Application/Recording usage does not
require Pipecat.

## Out of scope

- Org phone attach/detach in the database
- MinIO storage / `submit_call_recording`
- FastAPI `/answer` / WebSocket routes (call the XML helper from `apps/runtime`)
- Agent config / `ProviderAuth` credential lookup (caller injects auth)

---

Full documentation: [Telephony model](../../docs/guides/concepts/telephony-model.md) · [Adding a telephony provider](../../docs/developer/guides/adding-a-telephony-provider.md) · [Telephony package](../../docs/developer/services/telephony.md)
