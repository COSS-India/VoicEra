---
title: Go To Market (Go2Market)
description: OBD outbound, DID–WebSocket mapping, and µ-law audio streaming for Go2Market.
---

Go To Market (`go2market`) is a telephony provider under `apps/telephony/providers/go2market`. Unlike Vobiz and Plivo, it does not use answer Stream XML for live media. Outbound dials go through their OBD API with a WebSocket URL in the campaign payload; inbound DID calls open that same agent WebSocket after you register the DID via their DID-WebSocket API.

<Note>
Vobiz, Plivo, Vodafone Idea, and Go2Market are all supported. Pick a provider per agent in Integrations. This page covers Go2Market only; the shared model is in [Telephony model](../../guides/concepts/telephony-model).
</Note>

## Credentials (Integrations)

Auth is stored as one or more OBD profiles on the org `ProviderAuth` document. Each profile is:

| Field | Meaning |
| --- | --- |
| `serviceno` | 10-digit Go2Market service number (caller ID / DID). |
| `ukey` | User authentication key from the Go2Market portal. |
| `ivrtemplateid` | IVR template id from the Go2Market portal (for example `193`). |

In the UI these appear as a single **Go To Market profile** row. The first profile is also mirrored onto legacy fields (`auth_id` = serviceno, `auth_token` = ukey, `ivrtemplateid`) for dialing helpers.

Settings on the same config:

| Field | Default | Meaning |
| --- | --- | --- |
| `base_url` | `https://obd.voicensms.in/obd/OBDAPI/webresources` | OBD API base; DID-WebSocket root is derived from the same host. |
| `campaigntype` | `4` | Transactional OBD campaign type. |
| `retryatmpt` | `0` | Carrier-side retry attempts. |
| `retryduration` | `15` | Retry window in minutes. |

## Outbound dial

`POST /api/v1/calls/outbound` creates a `CallLog`, builds answer URLs, then calls `Go2MarketClient.initiate_call`. That rewrites the HTTP answer URL into an agent WSS and posts **CreateOBDCampaignPost**:

```
POST {base_url}/CreateOBDCampaignPost
Content-Type: application/json
```

```json
{
  "sourcetype": "1",
  "sendnow": "0",
  "schddate": "2026-10-29 10:42:00",
  "campaigntype": "4",
  "filetype": "2",
  "ukey": "<ukey>",
  "serviceno": "7971504853",
  "ivrtemplateid": "193",
  "retryatmpt": "0",
  "retryduration": "15",
  "msisdnlist": [
    {
      "phoneno": "7680958963",
      "WSS": "wss://voice.example.com/agent/{org_id}/{agent_id}?call_id={call_id}",
      "Param1": "wss://voice.example.com/agent/{org_id}/{agent_id}?call_id={call_id}",
      "callid": "{call_id}"
    }
  ]
}
```

| Field | Source |
| --- | --- |
| `phoneno` | Callee from the outbound request (normalized to 10 digits). |
| `serviceno` / `ukey` / `ivrtemplateid` | Matching OBD profile for the agent's from-number. |
| `WSS` and `Param1` | Agent WebSocket from `VOICE_SERVER_BASE_URL` / answer URL rewrite. |
| `callid` | VoicEra `call_id` when present on the answer URL. |
| `campaigntype`, `filetype`, `sourcetype`, `sendnow` | Fixed as above. |
| `schddate` | Current time in Asia/Kolkata; ignored by the carrier when `sendnow` is `0`. |

There is **no campaign id** in this request. `ivrtemplateid` is the IVR template from Integrations.

A successful carrier response is typically HTTP 200 with `{"status":"success","value":"accepted"}`. That means the dial was accepted, not that the handset rang. When the body has no provider call id, VoicEra stores its own `call_id` as `provider_call_sid`.

Implementation: `obd_client.py`, `application.initiate_call`, `helpers.answer_url_to_agent_wss`.

## DID ↔ WebSocket (inbound / attach)

Attaching a Go2Market number to an agent registers the agent's telephony answer WSS with Go2Market so inbound calls to that DID open the media stream. Detach deactivates the mapping (`isactive: false`); it does not delete the row.

Host root (derived from OBD `base_url` origin):

`https://obd.voicensms.in/obd/api/did-websocket`

| Operation | Method | Path | Body |
| --- | --- | --- | --- |
| List | `GET` | `/ukey/{ukey}` | — (`ukey` must be URL-encoded; `==` → `%3D%3D`) |
| Create | `POST` | `/` | `{ukey, did, websocketurl, isactive}` |
| Update URL | `PUT` | `/{did}` | `{ukey, websocketurl}` |
| Activate / deactivate | `PUT` | `/active` | `{ukey, id, isactive}` |

`did` is the 10-digit `serviceno`. The WebSocket URL must be the full agent path, with **no** `call_id` query for the saved inbound mapping:

`wss://{VOICE_SERVER_HOST}/agent/{org_id}/{agent_id}`

VoicEra's attach path calls `replace_did_websocket`: list → update + activate if the DID exists, else create; if create returns "DID already exists", update. Detach calls deactivate. Code: `did_websocket_client.py`, `application.link_number` / `unlink_number`.

The carrier may store the same number with a leading `0` as a separate row. List before debugging dropped inbound calls and deactivate obsolete rows.

## Media WebSocket

Go2Market connects to the agent WSS (`/agent/{org_id}/{agent_id}`). Event order matches their Audio Streaming Integration Guide v2.0:

1. `connected` — handshake; VoicEra ignores and keeps reading.
2. `start` — session metadata; VoicEra may echo the call id as `streamSid` when the carrier omits `streamSid`.
3. `media` — Base64 G.711 µ-law at 8 kHz, both directions.
4. `stop` / `dtmf` / `mark` as documented by the carrier.

Outbound media from VoicEra:

- Encoding: G.711 µ-law (`audio/x-mulaw`), 8,000 Hz, 8-bit, 64 kbps.
- Payload length: 160 bytes or a clean multiple (320, 480, … 4000).
- Silence pad byte: `0xFF`.
- JSON shape: `{event: "media", streamSid, media: {payload, chunk}}`.
- Barge-in: `clear` with `streamSid`.

`connected` must not be treated as an error. The shared helper `recv_media_stream_start` skips preamble events (`connected`) until `start`. Wire constants live in `wire.py`; encode/decode in `audio_codec.py`; frames in `serializers.py`.

## Application and recording stubs

`create_application` / `delete_application` / `update_application_name` are stubs (`app_id` = `go2market-app`). Live routing for inbound is the DID-WebSocket mapping; outbound embeds WSS in the OBD payload. Carrier-side recording helpers are stubs — call audio is captured by the Pipecat `AudioBufferProcessor` like other providers that lack a recording webhook.

## Related

* [Telephony model](../../guides/concepts/telephony-model)
* [Telephony package](telephony)
* [Telephony agents (wire)](../clients/telephony)
* [Adding a telephony provider](../guides/adding-a-telephony-provider)
* [Campaigns](../../guides/concepts/campaigns) — dispatcher uses per-call outbound for Go2Market (no bulk API)
* [Telephony troubleshooting](../../guides/troubleshooting/telephony)
