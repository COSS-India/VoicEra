---
title: Troubleshooting
description: Symptom-first index — find your error message, get the fix.
---

Organised by where the symptom shows up. If you are not sure which page applies, scan the table below for the message you actually saw.

<Note>
Before anything else: `make application-ps` shows which containers are up, and `docker compose logs -f <service>` shows why one is not. Most issues resolve from those two commands.
</Note>

## Symptom index

| What you see | Page |
| --- | --- |
| Stack will not start, containers restart-looping | [Common issues](common-issues) |
| `.env` not found, missing or empty secrets | [Common issues](common-issues) |
| Port already allocated | [Common issues](common-issues) |
| `ModuleNotFoundError: No module named 'apps'` | [Common issues](common-issues) |
| Connection refused to FerretDB | [Common issues](common-issues) |
| Call connects but there is no audio | [Voice and audio](voice-and-audio) |
| Audio in one direction only | [Voice and audio](voice-and-audio) |
| Speech is garbled, sped up, or robotic | [Voice and audio](voice-and-audio) |
| Agent will not stop talking when interrupted | [Voice and audio](voice-and-audio) |
| Greeting is cut off, or hold messages never play | [Voice and audio](voice-and-audio) |
| No transcript or recording after the call | [Voice and audio](voice-and-audio) |
| Provider cannot reach `/answer` | [Telephony](telephony) |
| `/answer` returns `400` | [Telephony](telephony) |
| Number will not attach or detach | [Telephony](telephony) |
| Recording never arrives from the provider | [Telephony](telephony) |
| Campaign stuck in a state, or paused itself | [Campaigns](campaigns) |
| Circuit breaker tripped | [Campaigns](campaigns) |
| Slot acquisition timeout, phone pool exhausted | [Campaigns](campaigns) |
| Worker not picking up jobs | [Campaigns](campaigns) |
| WSS fails behind a reverse proxy | [Deployment](deployment) |
| GPU not visible to a container | [Deployment](deployment) |
| Disk fills during a model build | [Deployment](deployment) |
| Volume permission errors | [Deployment](deployment) |

## The pages

* [**Common issues**](common-issues) — startup, environment, ports, imports, health checks.
* [**Voice and audio**](voice-and-audio) — anything you can hear, or cannot.
* [**Telephony**](telephony) — the provider boundary: webhooks, applications, numbers, recordings.
* [**Campaigns**](campaigns) — the orchestrator, ARQ worker, circuit breaker, and concurrency slots.
* [**Deployment**](deployment) — TLS, proxies, GPUs, disk, and volumes.

## Still stuck

Collect these before opening an issue: the failing command, `make application-ps`, the last 100 log lines from the affected container, and your `.env` with **every secret redacted**.

## Related

* [Daily operations](../operator/operations) — health endpoints and which logs matter
* [Ports and defaults](../../developer/reference/ports-and-defaults)
