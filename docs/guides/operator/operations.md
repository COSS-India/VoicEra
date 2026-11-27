---
title: Daily operations
description: Health checks, logs, backups, and capacity.
---

Keeping a running VoicEra stack healthy: what to probe, which logs answer which question, what to back up, and how to bring it back. Everything here assumes the reference [Docker Compose](../deployment/docker-compose) stack.

The loop this page describes:

```mermaid
flowchart LR
  H["Probe health<br/>:8000 · :7860"]
  L["Read the container<br/>that owns the question"]
  C["Check capacity signals<br/>docker stats · progress"]
  A["Act<br/>restart · scale · rotate"]
  B["Back up<br/>four volumes"]

  H --> L --> A
  H --> C --> A
  A --> H
  A -.->|"before risky changes"| B
```

## Health endpoints

Three health endpoints, none of them authenticated.

| Service | Endpoint | Returns |
| --- | --- | --- |
| API | `GET http://localhost:8000/health` | `{"status": "ok"\|"degraded", "database": "up"\|"down"}` |
| Runtime | `GET http://localhost:7860/health` | `{"status": "ok", "service": "voicera-runtime"}` |
| Model-server gateway | `GET http://localhost:8100/health` | `{"status": "healthy"\|"degraded", "upstreams": {…}}` |

```bash
curl http://localhost:8000/health
curl http://localhost:7860/health
```

The API's handler in `apps/api/app/main.py` pings FerretDB on every request. `degraded` means the process is alive but the database is unreachable — the API answers, and every route that touches data fails. Treat `degraded` as down.

The runtime's handler is a **static response**. It confirms the process is serving HTTP and nothing else: it does not check the API, MinIO, or any AI provider. A runtime returning `ok` can still fail every call. To test the path that matters, hit the answer webhook, which does reach the API to load the agent:

```bash
curl 'http://localhost:7860/answer?agent_id=YOUR_AGENT_ID&org_id=YOUR_ORG_ID'
```

Expect XML containing a `<Stream>` URL. An error here is a real fault; `/health` would not have shown it.

The gateway reports `degraded` when a deployed slot's upstream fails its check, and names which one in `upstreams`. It is a separate Compose project — see [Overview](../../developer/model-server/overview).

Compose's own healthchecks cover only `postgres`, `minio`, and `redis`. `api`, `runtime`, `arq-worker`, and `campaign-orchestrator` have **no** `healthcheck:` block, so `docker compose ps` shows them as running whether or not they are working. Probe them yourself:

```bash
make application-ps
```

## Which logs matter

Every long-lived service uses the `json-file` driver with `max-size: 10m` and `max-file: 3` — 30 MB per container, then the oldest file is dropped. That rotation is set on `postgres`, `ferretdb`, `api`, `minio`, `redis`, `arq-worker`, `campaign-orchestrator`, and `runtime`.

<Tip>
30 MB of rotation is roughly a day on a busy stack. A log line older than that is gone. Ship logs off the host before you need to investigate an incident from last week.
</Tip>

| Question | Container | Command |
| --- | --- | --- |
| Did an API request fail, and why? | `api` | `docker compose logs -f api` |
| Why did a call sound wrong or drop? | `runtime` | `docker compose logs -f runtime` |
| Why is a campaign not dialling? | `arq-worker` | `docker compose logs -f arq-worker` |
| Why did a campaign pause or complete early? | `campaign-orchestrator` | `docker compose logs -f campaign-orchestrator` |
| Is the database reachable? | `ferretdb`, `postgres` | `docker compose logs ferretdb postgres` |
| Did an artifact upload fail? | `minio` | `docker compose logs minio` |

Campaigns need both worker containers, and they answer different questions. The orchestrator decides *when* a batch runs; the ARQ worker *runs* it. A campaign stuck at zero progress is usually the worker; a campaign that stopped mid-list is usually the orchestrator. See [Workers and orchestrator](../../developer/services/workers).

For a live call, follow both sides at once — the runtime logs the pipeline, the API logs what the runtime asked it for:

```bash
docker compose logs -f runtime api
```

Turn up verbosity by setting `DEBUG=true` in the root `.env` and recreating the stack. `DEBUG` reaches the API through `env_file` only and is deliberately not interpolated in `docker-compose.yaml`; the reason is in [Environment variables](../../developer/reference/environment-variables).

## Backups

VoicEra keeps state in **four** places. A backup that covers fewer than four is incomplete.

| Store | Volume | Holds | Recreatable? |
| --- | --- | --- | --- |
| PostgreSQL (behind FerretDB) | `voicera_oss_ferretdb_postgres_data` | Users, organisations, agents, phone numbers, provider credentials, call logs, campaigns. | No |
| MinIO | `voicera_oss_minio_data` | Recordings, transcripts, campaign CSVs, knowledge PDFs. | No |
| Chroma | `voicera_oss_chroma_data` | Knowledge-base embeddings. | Yes, by re-uploading every PDF — at the cost of re-embedding. |
| Redis | `voicera_oss_redis_data` | ARQ job queue, campaign events, concurrency slots, circuit-breaker windows. | Mostly. Losing it drops in-flight jobs. |

Back up the database logically, through `pg_dump` against the `voicera_oss_postgres` container — not by copying the volume of a running Postgres:

```bash
docker exec voicera_oss_postgres \
  pg_dump -U admin -d postgres -Fc \
  > voicera-postgres-$(date +%F).dump
```

Use `-Fc` (custom format); it restores selectively and compresses. Substitute your own `MONGODB_USER` for `admin` if you changed it — Compose reuses that value as `POSTGRES_USER`.

MinIO copies out with the `mc` client, using the same image the stack already pulls:

```bash
docker run --rm --network voicera_app-network \
  -v "$PWD/minio-backup:/backup" \
  minio/mc:latest sh -c \
  "mc alias set src http://minio:9000 minioadmin <MINIO_ROOT_PASSWORD> && \
   mc mirror --overwrite src/voicera-calls /backup"
```

Check the network name with `docker network ls` — Compose prefixes `app-network` with the project name, which defaults to the directory name.

Chroma and Redis are file trees; copy them with a throwaway container while the stack is stopped:

```bash
docker run --rm \
  -v voicera_oss_chroma_data:/data:ro \
  -v "$PWD:/backup" \
  alpine tar czf /backup/chroma-$(date +%F).tar.gz -C /data .
```

Same command with `voicera_oss_redis_data` for Redis. Redis is worth capturing mainly so a restore does not resurrect stale queue entries; if you are willing to lose in-flight campaign batches, you can skip it and let the queue rebuild.

<Warning>
`docker compose down -v` deletes **all four volumes**: your database, every recording and transcript, every knowledge embedding, and the queue. There is no undo and no confirmation prompt. Use `make application-down` (which runs `docker compose down` without `-v`) unless you specifically intend to destroy the data.
</Warning>

## Restoring

Restore into a stack whose stores are running but whose application containers are stopped, so nothing writes underneath you.

```bash
docker compose up -d postgres ferretdb minio redis
```

PostgreSQL, from a `-Fc` dump:

```bash
docker exec -i voicera_oss_postgres \
  pg_restore -U admin -d postgres --clean --if-exists \
  < voicera-postgres-2026-09-01.dump
```

MinIO, mirroring back:

```bash
docker run --rm --network voicera_app-network \
  -v "$PWD/minio-backup:/backup" \
  minio/mc:latest sh -c \
  "mc alias set dst http://minio:9000 minioadmin <MINIO_ROOT_PASSWORD> && \
   mc mirror --overwrite /backup dst/voicera-calls"
```

Chroma, with the whole stack down:

```bash
docker run --rm \
  -v voicera_oss_chroma_data:/data \
  -v "$PWD:/backup" \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/chroma-2026-09-01.tar.gz -C /data"
```

Then bring the rest up and verify:

```bash
make application-up
curl http://localhost:8000/health
```

<Warning>
Restoring a database backup without the **matching `PROVIDER_AUTH_ENCRYPTION_KEY`** gives you rows you cannot read. Provider credentials are Fernet-encrypted with that key; a restore under a different key leaves every `ProviderAuth` blob permanently undecryptable and every telephony and model call failing. Back the key up alongside the dump, and treat losing it as losing the credentials.
</Warning>

## Rotating secrets

Three generated secrets, three very different rotation stories.

| Secret | Rotating it costs | Procedure |
| --- | --- | --- |
| `SECRET_KEY` | Every issued JWT is invalidated. Users log in again. | Change it in `.env`, `docker compose up -d api arq-worker campaign-orchestrator`. Safe. |
| `INTERNAL_API_KEY` | The runtime cannot reach service routes until it also has the new value. | Change it in `.env`, then recreate **both** sides together — it is set on `api`, `arq-worker`, and `runtime`. |
| `PROVIDER_AUTH_ENCRYPTION_KEY` | **Every stored provider credential becomes unreadable.** | Re-enter every credential through `POST /api/v1/auth` after rotating. Plan the downtime. |

Rotating the Fernet key has no migration path in the code: `apps/api/app/services/secret_crypto.py` decrypts with exactly one key and raises `Failed to decrypt ProviderAuth credentials` for anything the current key cannot open. To rotate deliberately, export the credentials you need first (`GET /api/v1/auth/{provider}` returns secrets unmasked to an admin), change the key, restart, and re-upsert.

Infrastructure passwords — `MONGODB_PASSWORD`, `MINIO_ROOT_PASSWORD`, `REDIS_PASSWORD` — need coordinated changes because Compose interpolates each into more than one place. `MONGODB_PASSWORD` is also `POSTGRES_PASSWORD`, and changing it against an initialised Postgres volume does not change the existing database user. `REDIS_PASSWORD` is the easy one: Compose rebuilds `REDIS_URL` from it, so changing it and recreating is enough. Details in [Security hardening](../deployment/security-hardening).

## Redacting PII in transcripts

Set `PII_REDACTION_ENABLED=true` in `.env`, then recreate the runtime with `docker compose up -d runtime`. `docker compose restart runtime` does not re-read `.env`, so the old setting would stay in effect. Check it took with `docker compose exec runtime printenv PII_REDACTION_ENABLED`.

Redaction then applies in three places:

| Where | What is redacted |
| --- | --- |
| Stored transcript (`transcript.txt` in MinIO) | Every line, when the call ends, using the whole call as context. The History page, transcript download, OBD report and translate endpoint only ever see this redacted text. |
| Runtime logs | Every line the runtime writes through its logger: its own lines, Pipecat's (including `DEBUG` output such as `Generating TTS [...]`) and the STT adapters'. Digits inside long letter-and-digit tokens such as call IDs, UUIDs and object IDs are left intact so logs stay traceable. Tracebacks are redacted too (the error text often repeats the failing value) and are written without local variable values. Uvicorn's request lines do not pass through it; they carry paths and IDs, not transcript text. |
| Browser test panel | The live caller and agent text, as each line arrives. The agent's token-by-token text streams (`bot-llm-text`, `bot-tts-text`) are not sent while redaction is on; the panel does not use them. |

Every detected item is replaced with the same placeholder, `[REDACTED_TEXT]`, whatever its type. A per-type label such as `[REDACTED_PHONE]` would tell anyone reading the transcript what kind of detail was there, which helps them guess it from the rest of the conversation. The types below are what is detected; their names are used only to choose types in `PII_REDACTION_ENTITIES`, and never appear in redacted text.

| Type | What is detected |
| --- | --- |
| `EMAIL` | Email addresses, typed (`a.b@example.com`) or spoken (`a dot b at example dot com`) |
| `PHONE` | Indian mobile numbers, with or without `+91` |
| `AADHAAR` | 12-digit Aadhaar-style numbers (Verhoeff-checked) |
| `PAN` | PAN numbers, including spelled out (`a b c d e 1 2 3 4 f`) |
| `CARD` | Payment card numbers (Luhn-checked) |
| `DOB` | Full dates: `15/12/2021`, `15-12-2021`, `15 12 2021`, `15 December 2021`, `December 15, 2021`, `15 दिसंबर 2021`, `15 ಡಿಸೆಂಬರ್ 2021` |
| `OTP` | Four to eight digits right after "OTP", or given in reply to the agent asking for one |
| `NUMBER` | Any other run of nine or more digits, or seven or more read out one digit at a time (landlines, account numbers, partial identifiers) |

**Numbers spoken as words.** Speech recognition writes numbers the way they were said ("nine eight seven six ...", `नौ आठ सात ...`, `ಒಂಬತ್ತು ಎಂಟು ...`). The redaction reads these as digits first. English, Hindi and Kannada are covered in full: digits, teens, tens and compounds (`ninety eight`, `अट्ठानवे`, `ತೊಂಬತ್ತೆಂಟು`), "double"/"triple", and years (`twenty twenty one`, `दो हज़ार इक्कीस`). Marathi, Bengali, Gujarati, Punjabi, Odia, Tamil, Telugu and Malayalam are covered for the digits zero to nine, which is how phone numbers and IDs are normally read out.

**Digit grouping.** Digits count as one identifier only when they are written together (`9876543210`, `9,876,543,210`), one digit at a time (`9 8 7 6 5 4 3 2 1 0`, `9, 8, 7, 6, ...`), in a grouping that identifier is read out in (phone 5-5, 3-3-4, 4-3-3 or in pairs; Aadhaar 4-4-4; card 4-4-4-4 or 4-6-5), or, when spoken as words, in pairs (`ninety eight seventy six ...`). A phone number in any other grouping (`9876 54 3210`) is redacted when the turn, or the speaker's previous turn, mentions a phone or number (`number`, `mobile`, `phone`, `नंबर`, `ಮೊಬೈಲ್`, ...). Aadhaar numbers must also pass the Verhoeff check and card numbers the Luhn check. Several numbers spoken in a row, such as prices (`2400 2500 2600`, `twenty four hundred, twenty five hundred`), are left as they are.

**Prices and quantities.** Numbers spoken with a quantity word or unit are amounts, not identifiers, and are not read as digits: `two thousand four hundred rupees`, `दो हज़ार चार सौ रुपये`, `पांच छह सात आठ नौ दस किलो`, `ಎರಡು ಸಾವಿರ ನಾಲ್ಕು ನೂರು ರೂಪಾಯಿ`. The same goes for numbers after `Rs` or `₹`, and for a long digit run followed by a unit (`123456789 rupees`). Words treated as quantities include hundred, lakh, crore, सौ, लाख, करोड़, ನೂರು, ಲಕ್ಷ, ಕೋಟಿ, and units such as rupees, kilo, quintal, acre, litre, percent, days and years in English, Hindi and Kannada.

**Whole-call context (stored transcript only).** Because the transcript is redacted when the call ends, it also catches:

- a number split over turns by the same speaker, for example `nine eight seven six` and then `five four three two one zero`, with up to one turn by the other speaker in between. A part typed in groups (`98`, then `76 54 32 10`) is joined when the call mentions a phone or number there;
- part of a number given in full elsewhere in the call, such as the agent repeating the last eight digits (five or more digits);
- an OTP, or a spoken email, given in reply to the agent asking for one.

The logs and the test panel are redacted line by line as the call happens, so they cannot wait for the rest of a split number. Instead they also mask any run of four or more digits read out one digit at a time, typed or as words (`nine eight seven six`, `1, 2, 3, 4`). Numbers said in pairs or as years (`twenty twenty five`) are not masked by this rule.

To redact only some of these, list them in `PII_REDACTION_ENTITIES`, for example `PHONE,EMAIL`.

Limits to know about:

- Redaction is permanent. The original text is not kept anywhere. During a call the text is held in the runtime's memory, as it already is in the LLM context, and dropped once the transcript is written.
- The setting applies to the whole deployment, not to individual organisations.
- Transcripts stored before the setting was turned on are not changed.
- Names and postal addresses are not detected.
- Romanised Hindi number words (`ek do teen`) are not read as digits, because `do`, `teen` and `char` are also English words. Pair-read numbers in languages other than English, Hindi and Kannada are not either.
- A spoken email of the form `name at domain dot org` is redacted only with a sign that it is an email: a dot, underscore or digits in the name, "at the rate", a known mail provider (`gmail`, `yahoo`, `outlook`, ...), or the word "email" in the same or the previous turn. Otherwise it could be a website.
- A six-digit PIN code read out one digit at a time is kept; seven or more digits read that way are redacted. The last four digits of a number on their own are kept.
- A phone number in an unusual grouping of digits (`9876 54 3210`) is detected only with a phone or number word nearby. Other identifiers in unusual groupings are not detected.
- A number said right before a unit is kept even if it is an identifier (`nine eight seven six rupees`).
- Three price-like groups of four digits that happen to pass the Aadhaar check (about 1 in 10) are still redacted as Aadhaar.
- Call recordings are covered separately: see [Call recordings](#call-recordings).
- Logs from other services (API, worker, model server) are not redacted.

## Call recordings

Each call can have two recordings:

- **The system recording** (`recording.wav` in MinIO), made by the runtime itself, with the caller and the agent mixed into one track.
- **The carrier recording**, made by the telephony provider (Plivo, Vi, Vobiz, Go2Market) and downloaded into MinIO after the call. The carrier also keeps its own copy on its side.

Two settings in `.env` decide what is recorded. As with PII redaction, recreate the runtime after a change with `docker compose up -d runtime`; `restart` does not re-read `.env`.

| `CALL_RECORDING_ENABLED` | `PII_REDACTION_ENABLED` | System recording | Carrier recording |
| --- | --- | --- | --- |
| `true` (default) | `false` | Stored as recorded | Started and stored |
| `true` | `true` | Stored with PII muted | Not started, not stored |
| `false` | either | Not made | Not started, not stored |

**How muting works.** When the call ends, the transcript is redacted first. Every caller utterance and every agent sentence that had something redacted is then replaced with a quiet 1 kHz tone in the recording, on that speaker's side only, with a short margin either side. The tone is the same whatever was removed, like `[REDACTED_TEXT]` in the transcript. Caller utterances with four or more digits read out are muted too, even where the transcript keeps them. Only the muted recording is uploaded: the unmuted audio stays in the runtime's memory and is dropped. If muting fails for any reason, the recording is not stored at all rather than stored unmuted. The recording keeps its full length, so the transcript's timestamps still line up with it.

**Why carrier recordings are not stored with redaction on.** A carrier recording starts on the carrier's clock and uses its own audio processing, so the muting cannot be lined up with it reliably, and the carrier keeps its own copy anyway. Carrier recording webhooks are acknowledged with `200` and not downloaded.

Limits to know about:

- Muting follows the text redaction. Whatever it does not detect (names, postal addresses), or what the speech recognition misheard, is not muted either.
- The unit is a whole caller utterance or a whole agent sentence. The speech engines give no word timings, so single words cannot be muted.
- An agent sentence that was cut off by an interruption is muted if anything in that agent turn was redacted.
- Recordings stored before the setting was turned on are not changed.
- A carrier can still record a call if recording is configured in your own carrier account or dashboard. Turn it off there too, and delete copies the carrier already holds. That is outside VoicEra.
- Links to recordings in carrier reports (for example Vi's call report) point to the carrier's copy.

## Capacity signals

VoicEra exposes no metrics endpoint. Capacity is read from the API, from Docker, and from the logs.

| Signal | Where | What it means |
| --- | --- | --- |
| Concurrent calls versus `DEFAULT_ORG_CONCURRENCY_LIMIT` | `.env`, default 10 | The ceiling on simultaneous calls per organisation. A campaign that never reaches its `max_concurrency` is being held here. |
| Campaign `processed_rows` rate | `GET /api/v1/campaign/{id}/progress` | Flat while `state` is `running` means slots, worker, or schedule window. |
| Runtime CPU | `docker stats voicera_oss_runtime` | Each live call is one WebSocket and one Pipecat pipeline in **one** container. This saturates first. |
| API CPU and memory | `docker stats voicera_oss_api` | The API also does RAG ingest in-process, so a large PDF upload shows here. |
| Redis memory | `docker compose exec redis redis-cli -a <REDIS_PASSWORD> INFO memory` | Queue depth and circuit-breaker windows. Steady growth means jobs are not being consumed. |
| MinIO disk | `docker system df -v` | Recordings dominate. Nothing prunes them — there is no retention policy in the code. |
| Postgres volume size | `docker system df -v` | Call logs grow without bound. |

Scale in this order, because it matches where the load actually lands: runtime first (one WebSocket per live call), then the ARQ worker, then the API. The campaign orchestrator does **not** scale — see [Production deployment](../deployment/production).

Neither recordings nor call logs are ever deleted by VoicEra. Budget disk for the full retention you intend, and prune deliberately.

## Restart and recovery

Routine restart, preserving all data:

```bash
make restart
```

`make restart` runs `application-down` then `application-up`. `application-down` runs `docker compose down` with no `-v`, so the volumes survive. `application-up` ensures the three secrets exist in `.env` before starting, which is why it is preferred over a bare `docker compose up`.

Restarting one service in place, without touching the others:

```bash
docker compose restart api
docker compose up -d --build api
```

Use `restart` after an environment change that the container reads at runtime; use `up -d --build` after a code or Dockerfile change.

What survives a restart, and what does not:

| Survives | Lost |
| --- | --- |
| Everything in the four volumes | Live calls — each is a WebSocket held by the runtime process |
| Queued ARQ jobs (Redis is persisted) | The orchestrator's in-memory `_batch_in_progress` and `_last_activity` state |
| Campaign state in the database | |

Losing the orchestrator's in-memory state is recoverable by design: the completion monitor runs every 60 seconds, re-reads every `running` campaign from the database, and falls back to `last_activity_at`, `last_batch_scheduled_at`, or `started_at` when it has no in-memory record. A campaign interrupted by a restart resumes within about a minute without intervention.

Recovery checks after any restart:

```bash
make application-ps
curl http://localhost:8000/health
curl http://localhost:7860/health
curl -s "$API/api/v1/campaign/" -H "Authorization: Bearer $TOKEN"
```

Confirm every campaign you expect to be `running` still is. One that was `paused` by the circuit breaker before the restart stays `paused` — that state is in the database, and only `POST /{campaign_id}/resume` clears it.

If the API will not start, read its logs first. The failure is almost always one of: `SECRET_KEY` missing (Compose refuses to interpolate and the stack never starts), FerretDB not yet accepting connections, or a startup exception from `initialize_database`, which is raised and logged before the process exits.

## Related

* [Docker Compose](../deployment/docker-compose)
* [Production deployment](../deployment/production)
* [Security hardening](../deployment/security-hardening)
* [Ports and defaults](../../developer/reference/ports-and-defaults)
* [Deployment troubleshooting](../troubleshooting/deployment)
