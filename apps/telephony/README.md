# Telephony

> Provider-agnostic clients for **Vobiz**, **Plivo**, **Vodafone Idea**, and **Go To Market**, shared by `apps/api` and `apps/runtime`.

[![Providers](https://img.shields.io/badge/providers-Vobiz%20%C2%B7%20Plivo%20%C2%B7%20VI%20%C2%B7%20Go2Market-brightgreen.svg)](#provider-catalog-for-appsapi--ui)
[![Registry](https://img.shields.io/badge/pattern-decorator%20registry-blue.svg)](#provider-catalog-for-appsapi--ui)

One `/answer` webhook serves Stream-XML carriers (Vobiz, Plivo). VI and Go2Market dial through OBD and open media WebSockets without that XML handshake. Per-provider modules own the differences.

## Install / import

Ensure `voicera/` is on `PYTHONPATH`:

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
```

Credentials and `base_url` are always injected. This package does **not** read
org `ProviderAuth`, the database, or environment variables for auth.

## Provider catalog (for `apps/api` / UI)

Same pattern as `apps.providers.schema`:

```python
from apps.telephony import Kind, provider_schemas, configuration_telephony, create_client
from apps.telephony.providers.vobiz.config import VobizConfig

schemas = provider_schemas(Kind.TELEPHONY)
# schemas includes vobiz, plivo, vi, go2market

defaults = configuration_telephony()
# {"telephony": {...}, "default_providers": {"telephony": "vobiz"}}

client = create_client(VobizConfig(auth_id="...", auth_token="..."))
```

Per-provider configs live in `providers/{name}/config.py` (Auth / Settings / Config).
Service creators (client, answer XML) register in `providers/{name}/service.py`
via `@register_client` and `@register_answer_xml`. Frame serializers register
in optional `serializer_service.py` (requires pipecat) and are loaded lazily
by the voice runtime only. Do not add provider if/elif chains to the
package-root `xml.py`, `calls.py`, or `serializers.py` facades.

| Area | Methods |
|------|---------|
| Application | `create_application`, `delete_application`, `update_application_name`, `link_number`, `unlink_number`, `list_numbers` |
| Outbound | `client.initiate_call(...)` or `initiate_outbound(provider, ...)` |
| Bulk (VI) | `initiate_bulk_calls`, `get_bulk_status` when the client supports them |
| Recording | `start_call_recording`, `fetch_recording_metadata`, `download_recording`, `wait_and_download_recording` (+ Plivo `list_recordings_for_call`) |
| Answer XML | `build_answer_stream_xml(provider, websocket_url, sample_rate=...)` |
| Frame serializers | `create_frame_serializer(provider, stream_sid=..., call_sid=..., sample_rate=...)` |
| Schemas | `apps.telephony.providers.{vobiz,plivo,vi,go2market}.schemas` |

Application / outbound methods return `{status, message, ...}` dicts. Recording
helpers return ids/bytes or `None`.

## Outbound call

Callers resolve credentials from `ProviderAuth` and build answer/hangup URLs; the library dials:

```python
from apps.telephony import VobizClient, initiate_outbound

client = VobizClient(auth_id, auth_token, base_url)
result = await client.initiate_call(
    from_number="+1555...",
    to_number="+1555...",
    answer_url="https://voice.example.com/answer?agent_id=...&org_id=...",
)

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
`hangup_method` when provided. Go2Market posts `CreateOBDCampaignPost` with the
agent WSS in `msisdnlist`; VI uses CPaaS OBD create + ingest.

## Answer XML (one `/answer` route)

The runtime keeps a single `/answer` webhook and dispatches by agent provider for
Stream-XML carriers:

```python
from apps.telephony import build_answer_stream_xml

xml = build_answer_stream_xml(
    provider,                 # "vobiz" | "plivo"
    websocket_url,
    sample_rate=16000,
)
```

VI media uses `/vi/stream`; Go2Market opens `/agent/{org}/{agent}` after DID mapping.
Callers should use the parent `build_answer_stream_xml` only where XML applies.

## Serializers (optional, needs pipecat)

```python
from apps.telephony.serializers import create_frame_serializer

serializer = create_frame_serializer(
    "go2market",              # or vobiz | plivo | vi
    stream_sid="stream-1",
    call_sid="call-1",
    sample_rate=16000,        # pipeline PCM rate; Go2Market wire µ-law is always 8 kHz
)
```

Not re-exported from `apps.telephony` so Application/Recording usage does not
require Pipecat.

## Out of scope

- Org phone attach/detach in the database
- MinIO storage / `submit_call_recording`
- FastAPI `/answer` / WebSocket routes (call the XML helper from `apps/runtime`)
- Agent config / `ProviderAuth` credential lookup (caller injects auth)

---

Full documentation: [Telephony model](../../docs/guides/concepts/telephony-model.md) · [Go To Market](../../docs/developer/services/go2market.md) · [Adding a telephony provider](../../docs/developer/guides/adding-a-telephony-provider.md) · [Telephony package](../../docs/developer/services/telephony.md)
