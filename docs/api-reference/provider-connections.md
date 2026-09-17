---
title: Provider connections
description: Named OpenAI-compatible endpoints, each with its own URL and key.
---

`apps/api/app/routers/provider_connections.py`, prefix `/api/v1/provider-connections`.

[Provider credentials](provider-auth) hold **one** credential set per provider per organisation, which is right for a vendor with one fixed host. A provider whose endpoint you supply needs the opposite: several endpoints at once, each with its own URL and its own key. Those are **provider connections**, stored in `ProviderConnections` and encrypted with the same `PROVIDER_AUTH_ENCRYPTION_KEY`.

Today one provider is connection-based: `openai_compatible`. Catalog entries advertise it — `GET /configuration/llm` and `GET /auth/catalog` mark such providers `"connection_based": true`. `POST /auth` refuses them with `422`.

## How an agent uses one

The agent stores only a reference. The endpoint and key are merged in by the runtime at call setup, so they never sit in the agent document:

```json
"llm_config": {
  "provider": "openai_compatible",
  "connection_id": "9f1c…",
  "model": "Qwen/Qwen3-8B-Instruct",
  "temperature": 0.4
}
```

`connection_id` is required for a connection-based provider, and must name an enabled connection in the caller's organisation. Sending `base_url` or `api_key` inside `llm_config` is rejected, exactly as for any other provider's secrets.

## `GET /provider-connections`

Bearer. Every connection in the organisation, `api_key` masked. Optional `provider` and `enabled_only=true` query filters.

## `POST /provider-connections`

Bearer, `admin` or `super_admin`. `201`.

```json
{
  "provider": "openai_compatible",
  "name": "Local vLLM",
  "base_url": "http://vllm.internal:8000/v1",
  "api_key": "sk-local",
  "models": ["Qwen/Qwen3-8B-Instruct"],
  "default_model": "Qwen/Qwen3-8B-Instruct",
  "supports_tools": true,
  "enabled": true
}
```

`name` must be unique in the organisation (`409` otherwise). A non-connection-based provider returns `422`. `api_key` accepts a list for rotation; the runtime uses the first entry.

`supports_tools` declares that the endpoint implements OpenAI tool calling — a knowledge base in `"tool"` mode requires it. The provider id cannot tell you this, because the operator chooses what the URL points at.

## `POST /provider-connections/probe`

Bearer, `admin` or `super_admin`. Reaches an endpoint that has not been saved yet — the dashboard's **Test connection** button.

```json
{ "base_url": "http://vllm.internal:8000/v1", "api_key": "sk-local" }
```

Returns `{ok, models, latency_ms, error, note}`. Unreachable is a normal `200` with `ok: false`, not an error status.

`GET /models` is tried first, because a published list is what fills the agent's model picker. **It is not required.** Plenty of OpenAI-compatible servers implement only `/chat/completions`; when the list is missing the check falls back to a one-token completion, and `note` says to enter model ids by hand. Pass `model` so that fallback has something to ask for — the dashboard sends the connection's default model.

Outcomes:

| Result | Meaning |
|---|---|
| `ok: true` with `models` | The endpoint publishes a list; it fills the model picker. |
| `ok: true`, empty `models` | Reachable via `/chat/completions`. Type model ids yourself. |
| `ok: false`, `rejected the API key` | The endpoint answered `401`/`403` — the URL is right, the key is not. |
| `ok: false`, `No /models and no /chat/completions` | Wrong base URL. Give the root, e.g. `http://host:8080/v1`. |

A `base_url` ending in `/chat/completions`, `/completions`, or `/responses` is trimmed to its root on save — the OpenAI client appends the operation itself, and pasting the full URL from a vendor's docs is the usual mistake.

## `GET` / `PATCH` / `DELETE /provider-connections/{id}`

Bearer; `PATCH` and `DELETE` need `admin` or `super_admin`. `PATCH` writes only the fields you send — an omitted `api_key` keeps the stored one, and a changed `base_url` clears `verified_at`. `DELETE`, and a `PATCH` setting `enabled: false`, both return `409` while any agent still references the connection, naming the agents — a disabled endpoint fails the agent's next call setup exactly as a deleted one does.

## `POST /provider-connections/{id}/test`

Bearer, `admin` or `super_admin`. Probes a stored connection and, on success, caches the returned model list and stamps `verified_at`.

## `GET /provider-connections/{id}/resolved`

Bearer, `admin` or `super_admin`. Returns the decrypted `{base_url, api_key}`. This is what the runtime calls with its bot token at call setup; the bot token carries the admin role.

## Endpoint safety

The API fetches `base_url` server-side when you test it, so the host is validated on save:

* `http://` or `https://` only.
* Cloud metadata addresses (`169.254.169.254`, `fd00:ec2::254`) are refused. Private ranges stay allowed — a self-hosted model on the LAN is the point.
* `PROVIDER_CONNECTION_ALLOWED_HOSTS` narrows it to a comma-separated allowlist when set.
* Redirects are never followed, and `PROVIDER_CONNECTION_PROBE_TIMEOUT` (default `8.0` seconds) bounds the probe.

## Related

* [Provider credentials](provider-auth) — one key set per vendor per organisation
* [Configuration](configuration) — provider catalogs and the `connection_based` flag
* [Agents](agents) — where `llm_config.connection_id` is stored
