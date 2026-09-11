---
title: Quickstart
description: From an empty machine to a working voice agent, in order.
---

Three pages, meant to be read in sequence. Together they get the stack running and ready to use.

<Note>
Total time is roughly 20 minutes, most of it Docker pulling images. You need Docker and one AI provider API key.
</Note>

## The path

| Step | Page | What you end with |
| --- | --- | --- |
| 1 | [Prerequisites](prerequisites) | A machine that can run the stack, and the accounts you need. |
| 2 | [Install and run](install-and-run) | Ten containers up, API answering on `:8000`, dashboard on `:3000`. |
| 3 | [Generated secrets and defaults](secrets-and-defaults) | Knowing what was generated for you and what to change. |

Once the stack is up, build your first agent and place your first call from the dashboard — no terminal needed:

* [Create your first agent](../dashboard/create-an-agent)
* [Test and call with your agent](../dashboard/make-a-call)

Prefer the API? See [Recipes](../../api-reference/recipes).

## Before you start

You do **not** need a telephony account to try VoicEra. A `websocket` agent runs entirely in the browser and needs only an STT, TTS, and LLM key. Add telephony when you want real phone numbers.

<Warning>
Run `make application-up`, not a bare `docker compose up`. It generates `SECRET_KEY`, `INTERNAL_API_KEY`, and `PROVIDER_AUTH_ENCRYPTION_KEY` into `.env`; without them the stack starts misconfigured.
</Warning>

## Where next

Once a call works:

* [Architecture](../concepts/architecture) — what you just started
* [Running a campaign](../operator/running-a-campaign) — outbound at volume
* [Security hardening](../deployment/security-hardening) — before anyone else can reach it
