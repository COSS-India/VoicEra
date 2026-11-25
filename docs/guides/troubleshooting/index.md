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
| Stack will not start, containers restart-looping | [Common issues](/docs/guides/troubleshooting/common-issues) |
| `.env` not found, missing or empty secrets | [Common issues](/docs/guides/troubleshooting/common-issues) |
| Port already allocated | [Common issues](/docs/guides/troubleshooting/common-issues) |
| `ModuleNotFoundError: No module named 'apps'` | [Common issues](/docs/guides/troubleshooting/common-issues) |
| Connection refused to FerretDB | [Common issues](/docs/guides/troubleshooting/common-issues) |
| Call connects but there is no audio | [Voice and audio](/docs/guides/troubleshooting/voice-and-audio) |
| Audio in one direction only | [Voice and audio](/docs/guides/troubleshooting/voice-and-audio) |
| Speech is garbled, sped up, or robotic | [Voice and audio](/docs/guides/troubleshooting/voice-and-audio) |
| Agent will not stop talking when interrupted | [Voice and audio](/docs/guides/troubleshooting/voice-and-audio) |
| Greeting is cut off, or hold messages never play | [Voice and audio](/docs/guides/troubleshooting/voice-and-audio) |
| No transcript or recording after the call | [Voice and audio](/docs/guides/troubleshooting/voice-and-audio) |
| Provider cannot reach `/answer` | [Telephony](/docs/guides/troubleshooting/telephony) |
| `/answer` returns `400` | [Telephony](/docs/guides/troubleshooting/telephony) |
| Number will not attach or detach | [Telephony](/docs/guides/troubleshooting/telephony) |
| Recording never arrives from the provider | [Telephony](/docs/guides/troubleshooting/telephony) |
| Campaign stuck in a state, or paused itself | [Campaigns](/docs/guides/troubleshooting/campaigns) |
| Circuit breaker tripped | [Campaigns](/docs/guides/troubleshooting/campaigns) |
| Slot acquisition timeout, phone pool exhausted | [Campaigns](/docs/guides/troubleshooting/campaigns) |
| Worker not picking up jobs | [Campaigns](/docs/guides/troubleshooting/campaigns) |
| WSS fails behind a reverse proxy | [Deployment](/docs/guides/troubleshooting/deployment) |
| GPU not visible to a container | [Deployment](/docs/guides/troubleshooting/deployment) |
| Disk fills during a model build | [Deployment](/docs/guides/troubleshooting/deployment) |
| Volume permission errors | [Deployment](/docs/guides/troubleshooting/deployment) |

## The pages

* [**Common issues**](/docs/guides/troubleshooting/common-issues) — startup, environment, ports, imports, health checks.
* [**Voice and audio**](/docs/guides/troubleshooting/voice-and-audio) — anything you can hear, or cannot.
* [**Telephony**](/docs/guides/troubleshooting/telephony) — the provider boundary: webhooks, applications, numbers, recordings.
* [**Campaigns**](/docs/guides/troubleshooting/campaigns) — the orchestrator, ARQ worker, circuit breaker, and concurrency slots.
* [**Deployment**](/docs/guides/troubleshooting/deployment) — TLS, proxies, GPUs, disk, and volumes.

## Still stuck

Collect these before opening an issue: the failing command, `make application-ps`, the last 100 log lines from the affected container, and your `.env` with **every secret redacted**.

## Related

* [Daily operations](/docs/guides/operator/operations) — health endpoints and which logs matter
* [Ports and defaults](/docs/developer/reference/ports-and-defaults)
