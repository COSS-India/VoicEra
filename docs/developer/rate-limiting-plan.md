# Rate limiting and abuse control — implementation plan

Status: partially implemented. Landed so far, all gated behind
`RATE_LIMIT_ENABLED=false` by default (no behaviour change until enabled):

- **Layer 0** — primitives (`app/services/limits/`, `app/utils/client_ip.py`),
  config/settings, startup validation, the 429 handler, and fixes S3, S3b, S4,
  S6, S7.
- **Layer 1** — IP/email limits wired into `routers/users.py`.
- **Layer 2** — the call-admission funnel (`app/services/call_admission.py`),
  wired into `routers/calls.py`'s `/outbound`, `/inbound`, `/web` endpoints.
  Org concurrency and per-IP concurrency (web calls only) are fully
  enforced.
- **Layer 3** — the runtime duration guard
  (`apps/runtime/services/pipecat/duration_guard.py`), wired into
  `run_with_lifecycle`. `end_reason` added to `CallLogUpdateRequest` /
  `CallLogResponse` so the cap is visible in call logs rather than a
  mystery hangup. The ceiling (`MAX_CALL_DURATION_CEILING_SECONDS`) is
  applied unconditionally, regardless of any per-agent
  `call_timeout_seconds` override. Like every other layer, the guard is
  only *armed* when `RATE_LIMIT_ENABLED=true` — see §8c for why the
  "unconditional" in that section means "no per-org or per-IP exemption",
  not "runs before the feature is switched on".
- **Layer 4** — usage accounting, hooked into
  `call_log_service.patch_call_log` at the same `_has_end_time` guard that
  already makes `duration` idempotent against a redelivered hangup webhook,
  so the usage increment inherits that idempotency for free. Gated by
  `RATE_LIMIT_ENABLED` like every other layer — zero new Redis writes while
  it's off. The org daily quota check added in Layer 2 now reads real
  consumption.

**Deliberately not done, by explicit decision, not oversight:**

- **Layer 2b is skipped.** No signed WebSocket admission token, no change to
  the agent WebSocket's accept path. This means S1 and S2 remain open: the
  runtime's self-mint fallback (`apps/runtime/routes/agent.py:79-99`) can
  still join a web call that Layer 2 would have denied, without ever going
  through the API. Layer 2 fully protects the ad-hoc REST admission path
  (`/calls/outbound`, `/calls/inbound`, `/calls/web` called directly) but is
  bypassable on the browser test-call path until 2b lands. Tracked, not
  forgotten.
- The org-override schema in §6 (`Organizations.daily_call_seconds`,
  `.max_call_duration_seconds`) is read by `limits/policy.py` but nothing
  writes it yet — no admin UI or API to set a per-org override exists, so
  every org currently runs on the env defaults. Not a gap in what's shipped
  (the defaults are fully enforced), just an unbuilt convenience.

Tests: `apps/api/tests/test_limits.py`, `apps/api/tests/test_call_admission.py`,
`apps/api/tests/test_call_log_usage_accounting.py`,
`apps/runtime/tests/test_duration_guard.py`.

Scope: `apps/api` (FastAPI backend) and `apps/runtime` (Pipecat voice runtime).

This file is intentionally not listed in `docs.json`, so it is not published to the
docs site. Move it into `docs/developer/reference/` and add a nav entry once the
work lands and this becomes reference material rather than a plan.

---

## 1. Goals

Bound abuse and runaway cost across four axes:

| Axis | Limit | Enforced at |
|---|---|---|
| Organisations created per IP | hourly + daily | `POST /users/signup` |
| Concurrent calls per IP | absolute | call admission (web calls) |
| Call-seconds per org per day | daily quota | call admission + usage counter |
| Duration of a single call | hard cap | voice runtime watchdog |

Plus two limits that fall out of the same primitives for near-zero extra cost, and
which are the more commonly exploited holes in practice:

| Axis | Limit | Enforced at |
|---|---|---|
| Auth attempts per IP | per minute | `/users/login`, `/forgot-password`, `/reset-password` |
| Password-reset mails per email address | per hour | `/users/forgot-password` |

Non-goals: billing, metering for invoices, per-endpoint quota tiers, an admin UI for
editing limits, and a global request-rate limit on every route. See §11.

## 2. Design principles

1. **Reuse the existing limiter.** `apps/api/app/services/call_concurrency/rate_limiter.py`
   already implements Redis-Lua concurrency slots and a sliding-window token bucket.
   Extend it; do not introduce `slowapi` or a second limiter.
2. **No new infrastructure.** Redis is already a dependency of `apps/api`
   (`redis[hiredis]`), already runs in compose with a password
   (`docker-compose.yaml:161`), and is already on the call path via the campaign
   orchestrator.
3. **Enforce at admission, not in middleware.** Limits are applied with explicit
   FastAPI dependencies on the routes that need them, so the limit is visible in the
   route signature and costs nothing on routes that do not.
4. **Org-scoped limits take the org as their subject.** Who submits the request is
   irrelevant to a per-org quota. Only *per-IP* limits care about the caller, and only
   those may ever be exempted by caller identity. See §8 — getting this wrong silently
   disables the two headline quotas.
5. **Every Redis key has a TTL.** No cleanup job, no unbounded growth.
6. **Fail loudly, degrade predictably.** A limiter outage must not take down signup or
   calls, but every bypass is logged and countable.

## 3. Current state

### Already implemented

- `services/call_concurrency/rate_limiter.py` — Redis-Lua primitives: sliding-window
  token bucket (`acquire_token`), atomic org + scope concurrency slots backed by
  sorted sets, from-number pool, and `call_id → slot` mappings for release on hangup.
- `services/call_concurrency/service.py` — `acquire_org_slot` / `bind_call_slot` /
  `release_call_slot`, with the per-org limit resolved from the database.
- A slot-release path that **does** reach non-campaign calls, despite its naming: the
  runtime's `finalize_call` (`apps/runtime/services/pipecat/lifecycle.py:30`) calls
  `notify_campaign_call_status` unconditionally for any call with a `call_id`, which
  hits `POST /campaign/internal/call-status` (`routers/campaign.py:505`) →
  `handle_call_terminal` (`services/campaign/status_processor.py:18`), which releases
  the slot at line 25 *before* the `if not campaign_id: return` guard. Layer 2 depends
  on this. Its fragility is covered in §10.

### The request path

Both proxy hops matter for §7, and only one of them is in `deploy/`:

```
browser ──▶ nginx ──▶ Next.js server ──▶ apps/api        (all /api/v1/* traffic)
            │          (next.config.ts rewrites)
            │
            └──▶ nginx ──▶ Next.js server ──▶ apps/runtime  (wss://…/agent/…)
```

`frontend/next.config.ts` rewrites `/api/v1/:path*` → `API_PROXY_TARGET` and
`/agent/:orgId/:agentId` → `RUNTIME_PROXY_TARGET`. The browser only ever talks
same-origin to Next; `NEXT_PUBLIC_API_URL` defaults to the relative `/api/v1`. So
**the API is two proxy hops from the client, not one.**

nginx's `location /` sets `X-Forwarded-For` via `$proxy_add_x_forwarded_for`
(`deploy/SETUP.md:116`). Its `location /agent/` block (`deploy/SETUP.md:123`) sets no
forwarding headers at all — the runtime therefore has no client-IP context by
construction, which §8 relies on.

`apps/api` runs as a **single** uvicorn process (`apps/api/Dockerfile:21`,
`docker-compose.yaml:110` — no `--workers`). In-process caches are therefore
process-global today, but must not *assume* that.

### Gaps

| # | Gap | Evidence |
|---|---|---|
| G1 | Concurrency slots are acquired **only** by the campaign dispatcher. Ad-hoc outbound, inbound and web calls bypass every limit. | `services/campaign/campaign_call_dispatcher.py:65` is the sole caller of `acquire_org_slot` |
| G2 | `behaviour.call_timeout_seconds` exists in the API schema and the dashboard, but nothing enforces it. Calls can run unbounded. | `models/schemas.py:228`, `frontend/src/lib/agent-mapper.ts:44`; `PipelineWorker` is built with `idle_timeout_secs=None` at `apps/runtime/services/pipecat/factory.py:148` |
| G3 | No IP awareness anywhere in the codebase. `POST /users/signup` creates a user and an organisation unauthenticated, with no limit. | `routers/users.py:31` |
| G4 | No usage accounting. Call duration is computed but never aggregated. | `services/call_log_service.py:42` |
| G5 | No 429 response path, no `Retry-After`, no limit configuration. | — |

## 4. Security review findings

These came out of reviewing the call path end to end. Items marked **blocking** must
be fixed as part of this work, because without them the limits below are advisory
only — an attacker simply does not take the code path that checks them.

### S1 — The agent WebSocket is unauthenticated (blocking)

`apps/runtime/routes/agent.py:24` — `@router.websocket("/agent/{org_id}/{agent_id}")`
accepts any connection at line 27. No token, no signature, no origin check. If
`call_id` is absent the runtime mints a web call itself (`agent.py:79-99`) using its
own internal bot credentials and starts the full STT → LLM → TTS pipeline.

`agent_id` is a uuid4 (122 bits, unguessable), but the `org_id`/`agent_id` pair is
handed to every browser that opens the dashboard's test-call widget. Anyone who has
legitimately used a public agent once can replay that pair indefinitely and burn
provider spend, from any number of connections, without ever touching the API.

Every org-scoped quota in this plan is enforced at API call admission. An attacker on
this path never calls the API. **The quotas are unenforceable until this is closed.**

Fix (Layer 2b): the API mints a short-lived signed session token when it admits a web
call; the runtime requires and verifies it before `websocket.accept()` and rejects
with close code 1008 otherwise. The runtime's self-mint fallback is deleted, not
merely guarded — while it exists, omitting `call_id` is a one-request bypass of
everything in §6. Details and the crypto choices in Layer 2b.

### S2 — The runtime ignores admission failures (blocking)

`apps/runtime/routes/agent.py:93-99` and `:158-164` — when `create_web_call` or
`create_inbound_call` raises `BackendError`, the runtime logs a warning and **runs the
pipeline anyway**, just without a `call_id`.

A 429 from call admission is a `BackendError`. Under the current code a rejected call
still runs, unmetered and unattributed, which is worse than not limiting at all. A
call with no `call_id` also never finalises (`runners.py:70` sets
`finalize_call=bool(call_id)`), so it never releases a slot or increments usage.

Fix: distinguish admission denial (HTTP 429/403) from transport failure in
`services/backend.py`. On denial, close the WebSocket with 1008 and a reason. On
transport failure, keep the existing lenient behaviour — a Redis or network blip
should not drop a live inbound call.

### S3 — `stale_call_timeout` is shorter than the proposed call cap

`rate_limiter.py:26` sets `stale_call_timeout = 1200` (20 min). The Lua in
`try_acquire_concurrent_slot_details` treats any slot older than that as dead and
removes it (`rate_limiter.py:90`).

With `MAX_CALL_DURATION_CEILING_SECONDS = 1800`, a legitimate 25-minute call has its
slot reaped while still active. The slot is then re-issued and the org exceeds its
concurrency limit silently.

Fix: derive it — `stale_call_timeout = MAX_CALL_DURATION_CEILING_SECONDS + 300`. The
reaper must always be strictly more patient than the hard cap it backstops.

**But not for the scope key.** The Lua applies one `stale_cutoff` to both the org zset
(`rate_limiter.py:86`) and the scope zset (`rate_limiter.py:96`). Raising it to 2100s
makes every leaked per-IP slot a 35-minute lockout at a limit of 2. The two reapers
must be tuned independently — see S3b.

### S3b — The scope zset needs its own, much shorter reaper (new)

Per-IP concurrency is a *new* consumer of the same Lua, with a far smaller limit and a
far higher cost of a false positive: one leaked slot out of two removes a user's
ability to place a test call for the full reaper window.

Fix: add a second `ARGV` carrying `scope_stale_cutoff` and apply it to the
`ZREMRANGEBYSCORE` on the scope key only. Default it to
`RATE_LIMIT_SCOPE_STALE_SECONDS = 900`. This is a three-line Lua change and is the
difference between a limit that annoys and a limit that pages.

### S4 — Token-bucket members collide under load

`rate_limiter.py:54` — `ZADD key now now`. The sorted-set member is the timestamp
itself. Two requests landing on the same float timestamp produce the same member, the
second `ZADD` overwrites rather than adds, `ZCARD` under-counts, and the limit lets
more through than configured. Exactly the concurrency at which the limit matters.

Fix: unique member, `f"{now}:{uuid4().hex[:8]}"`, matching the slot-id pattern already
used on line 79.

### S5 — `SECRET_KEY` is auto-generated when unset

`app/auth.py:22-32` — a missing `SECRET_KEY` produces a random per-process key with a
warning. The API runs single-worker today (§3), so this is currently a
restart-invalidates-all-JWTs bug rather than a cross-worker split — but the moment
`--workers` is added it also multiplies any key-derived counter by the worker count.

Fix: do not reuse `SECRET_KEY` for IP hashing. Introduce `RATE_LIMIT_IP_SALT` and
refuse to start when `RATE_LIMIT_ENABLED=true` and the salt is empty. Separately, a
missing `SECRET_KEY` should be a hard startup failure when `DEBUG=false`.

### S6 — `verify_api_key` compares with `!=`

`app/auth.py:134` — `if x_api_key != settings.INTERNAL_API_KEY`. Non-constant-time
comparison of a shared secret. The remotely observable timing signal is small, but the
fix is one line: `secrets.compare_digest`.

### S7 — `_get_redis` has a first-call race

`rate_limiter.py:28-33` — concurrent first calls each construct a client. Harmless
but wasteful. Use a module-level client created at import, or guard with an
`asyncio.Lock`. Also switch to `redis.register_script` so Lua bodies are sent once via
`EVALSHA` rather than on every evaluation.

### S8 — CORS is wildcard with credentials

`app/main.py:68-73` — `allow_origins=["*"]` together with `allow_credentials=True`.
Browsers reject that combination, so the practical effect today is that credentialed
cross-origin requests fail, but the intent is wrong and it will be "fixed" by someone
into a genuine vulnerability. Out of scope for this work; tracked here so it is not
lost. Restrict to `FRONTEND_URL` plus configured origins.

### S9 — Unauthenticated user-enumeration endpoint

`routers/users.py:138` — `GET /users/check/{email}` takes no auth dependency and
reports whether an address can join. Enumerable at speed. Covered by the per-IP auth
limit in §6, but the response should also be uniform rather than distinguishing
"unknown address" from "already a member".

### S10 — The telephony answer webhook is unauthenticated (new, flagged not fixed)

`apps/runtime/routes/telephony.py:43` — `@router.api_route("/answer")` is publicly
exposed at `voice.example.com` with **no provider signature verification**. It reads
`org_id`, `agent_id` and `call_id` from query parameters, and on a hangup event
patches the CallLog with `end_time_utc` and `status: completed` using the bot JWT for
that org.

`end_time_utc` is precisely the input to the duration computation that Layer 4's daily
quota is built on: setting it early truncates `duration` and under-counts the quota.
Cross-org exploitation requires guessing a uuid4 `call_id` or a provider SID, so this
is not trivially reachable, and it is not a blocker for this work. But it is an
unauthenticated write into the accounting layer and there is no webhook signature
verification anywhere in the repo.

Fix (separate change): verify the provider's webhook signature — Plivo and Twilio both
sign. Tracked here, alongside S8, so it is not lost.

## 5. Architecture

```
                 ┌──────────────── apps/api ────────────────┐
  client ─nginx─▶ Next ─┤  deps.py  →  limits/  →  Redis     │
                 │         │         counters / policy       │
                 │         └──→ call_admission.py ──→ call_concurrency (existing)
                 └──────────────────┬───────────────────────┘
                                    │ signed session token (S1)
                 ┌──────────────── apps/runtime ────────────┐
   media ──WS───▶ Next ─┤ token verify → duration_guard → pipeline │
                 └───────────────────────────────────────────┘
```

Note both hops. The Next server is a real proxy on *both* paths, not a build-time
detail — §7 depends on it.

Redis holds only ephemeral counters. Policy (the limits themselves) lives in env
settings with per-org overrides in the database. The runtime holds no limiter state:
its one job, the hard duration cap, needs only a deadline that travels with the
admission response.

### Key schema

| Key | Type | TTL | Purpose |
|---|---|---|---|
| `rl:{scope}:{subject}:{window_start}` | string counter | window length + 60s | Fixed-window counters (signup, auth, reset mail) |
| `concurrent_calls:{org_id}` | zset | 3600s | Existing org concurrency |
| `concurrent_calls:ip:{ip_hash}` | zset | 3600s | Per-IP concurrency, via the existing `scope_key` parameter |
| `usage:dur:{org_id}:{YYYYMMDD}` | integer | 48h | Call-seconds consumed today |
| `ws_nonce:{nonce}` | string | token TTL | Single-use marker for the Layer 2b session token |

`{subject}` is never a raw IP — see §7. Day boundaries are UTC; `YYYYMMDD` is computed
in UTC so that counters do not reset twice or skip on a DST change.

### Algorithms

**Fixed window** for the counter limits: one `INCR`, plus `EXPIRE` when the returned
value is 1, in a single Lua call. One round trip, one key, trivially correct. Its known
weakness is a burst of up to 2× the limit across a window boundary, which is
irrelevant for limits measured in "a handful per hour".

**Sliding window** (the existing `acquire_token`) stays where it is, for the campaign
dispatcher's per-second call pacing, where boundary bursts do matter.

**Concurrency** reuses `try_acquire_concurrent_slot_details`, which already evaluates
the org limit and a scope limit atomically — so per-IP concurrency needs only a
`scope_key` and a `scope_max_concurrent`. The one Lua change it does need is the
independent scope reaper cutoff from S3b.

## 6. Limit catalogue

| Scope | Key subject | Default | Setting |
|---|---|---|---|
| Successful org creations | IP | 2/hour, 5/day | `SIGNUP_ORGS_PER_IP_PER_HOUR`, `SIGNUP_ORGS_PER_IP_PER_DAY` |
| Signup attempts | IP | 10/hour | `SIGNUP_ATTEMPTS_PER_IP_PER_HOUR` |
| Auth attempts | IP | 10/minute | `AUTH_ATTEMPTS_PER_IP_PER_MINUTE` |
| Password-reset mails | email address | 3/hour | `RESET_MAILS_PER_EMAIL_PER_HOUR` |
| Concurrent calls | IP | 5 | `MAX_CONCURRENT_CALLS_PER_IP` |
| Concurrent calls | org | existing, 10 | `DEFAULT_ORG_CONCURRENCY_LIMIT` |
| Call-seconds per day | org | 14400 (4h) | `ORG_DAILY_CALL_SECONDS` |
| Single call duration | agent | 600s, ceiling 1800s | `MAX_CALL_DURATION_SECONDS`, `MAX_CALL_DURATION_CEILING_SECONDS` |

The per-IP concurrency default is 5, not 2. Two is the number the abuse case wants; it
is also low enough that a single leaked slot (§10) costs a legitimate user most of
their capacity for a 15-minute reaper window. Five is the number that survives the
leak. Tighten it after the shadow-mode run in §13 shows the real distribution.

Two counters for signup rather than one, deliberately: **attempts** catch the attacker
who probes with addresses that already exist, while **successes** cap the actual
resource being protected. A single counter would either let probing run free or let
one attacker exhaust the daily budget of every user behind the same NAT.

The reset-mail limit is keyed on the target email, not the requester's IP. Without it,
a distributed requester can mail-bomb a specific victim and burn the Mailtrap quota
while staying under every per-IP limit. As at every other point in this flow, the
response body and status must be identical whether the address exists or not, and
whether the limit was hit or not — otherwise the limiter itself becomes the
enumeration oracle.

### Per-org overrides

An override field already exists and is **flat**, not nested:
`campaign_repository.get_org_concurrent_limit` (`campaign_repository.py:45-52`) reads
`concurrent_call_limit` from the top level of the Organizations document. Do not
introduce a competing `limits.concurrency` key. Extend the existing shape:

```jsonc
// Organizations document
{
  "org_id": "a1b2c3",
  "concurrent_call_limit": 25,          // existing field, unchanged
  "daily_call_seconds": 86400,          // new, optional
  "max_call_duration_seconds": 1200     // new, optional; still clamped by the env ceiling
}
```

Resolved by `limits/policy.py`: per-org value → env default. Two constraints the
existing resolver does not meet, and that `policy.py` must:

- **It must cache.** `get_org_concurrent_limit` issues an uncached `find_one` per call
  and is invoked from `acquire_org_slot` (`call_concurrency/service.py:54-57`) on the
  hot path. Layer 2 puts that on every web, inbound and outbound call setup. Use a
  60-second TTL cache and have `get_org_concurrent_limit` delegate to `policy.py` so
  there is one resolver and one cache, not two that can disagree.
- **It must not block the event loop.** The resolver is synchronous pymongo called from
  an async function, in a single-worker process. On a cache miss, go through
  `run_in_threadpool`.

A per-worker cache is fine here; limits change rarely and a minute of skew is harmless.

`DEFAULT_ORG_CONCURRENCY_LIMIT` is currently read twice — `config.py:88` and
`constants/campaign.py:7-8` reads the same env var directly. Collapse to the settings
object while touching this.

## 7. Client IP resolution

New `app/utils/client_ip.py`.

```
TRUST_PROXY_HEADERS=false     # true in prod
TRUSTED_PROXY_HOPS=2          # see below — VERIFY, do not assume
RATE_LIMIT_IP_SALT=""         # required when limiting is enabled
```

Rules, in order:

1. `TRUST_PROXY_HEADERS=false` → use `request.client.host` and nothing else.
2. `TRUST_PROXY_HEADERS=true` → parse `X-Forwarded-For` and take the entry at index
   `-TRUSTED_PROXY_HOPS`. **Never the leftmost entry.** nginx appends via
   `$proxy_add_x_forwarded_for`, so the real client sits at the right-hand end; the
   leftmost is attacker-supplied and choosing it hands out a limit bypass via a single
   request header.
3. Normalise IPv6 to its **/64 prefix** before use. A single residential IPv6
   allocation is typically a /56 or /64 — limiting per /128 means an attacker rotates
   addresses for free and the limit means nothing.
4. Hash for storage: `sha256(RATE_LIMIT_IP_SALT + normalised_ip)[:16]`. Redis and logs
   never hold a raw client IP. 64 bits of key space is far beyond collision relevance
   at these cardinalities.

### The hop count must be measured, not assumed

There are two proxies in front of `apps/api` (§3), not one. Whether
`TRUSTED_PROXY_HOPS` is 1 or 2 depends on whether the Next rewrite proxy appends its
own address to `X-Forwarded-For` or forwards the header unchanged, which is a Next
implementation detail that has changed across releases.

Getting this wrong does not degrade gracefully. If the resolved subject collapses to
the Next container address, every limit in §6 becomes **global**: 2 org creations per
hour and 10 auth attempts per minute for the entire platform. That is a self-inflicted
outage, and it is worse than having no limiter. "Fails closed" is not a defence when
the failure mode is closed *for everyone*.

Required before Layer 1 ships with `TRUST_PROXY_HEADERS=true`:

- Measure it against the real stack. Add a temporary `X-Forwarded-For` echo to a debug
  route, drive it through nginx → Next from an external address, and read the chain.
- Add a permanent startup log line recording `TRUSTED_PROXY_HOPS` and, on the first N
  requests, the raw header and the resolved subject hash at INFO. An operator must be
  able to answer "is this limiting per user or per proxy?" from the logs.
- Alert on subject cardinality. If the distinct-subject count for the signup scope
  over an hour is 1, the resolution is wrong. This is a two-line check and it catches
  the failure before customers do.

Prefer, if the deployment allows it, having Next forward an explicit `X-Real-IP` and
reading that in preference to the hop count. Counting hops is fragile across a Next
upgrade in a way an explicit header is not.

Startup validation: refuse to start when `RATE_LIMIT_ENABLED=true` and
`RATE_LIMIT_IP_SALT` is empty (see S5).

## 8. Exemptions

Two independent mechanisms, deliberately not merged, because they exempt different
things.

### 8a. IP allowlist — exempts per-IP limits only

```
RATE_LIMIT_IP_ALLOWLIST=""    # comma-separated IPs and CIDRs, v4 and v6
                              # e.g. "203.0.113.7,198.51.100.0/24,2001:db8::/32"
```

Parsed once at settings load by a pydantic `field_validator` into a list of
`ip_network` objects (`strict=False`, so a bare address becomes /32 or /128). Matching
is a linear scan, sub-microsecond for a list of this size; a prefix tree would be
unjustified complexity.

**A malformed entry aborts startup.** It is not skipped with a warning: a typo'd CIDR
that silently disappears means limits fire against an address the operator believes is
exempt, and the failure surfaces as a confused customer rather than a log line.

An allowlisted address skips: the signup and auth windows, the reset-mail window, and
per-IP concurrency. It does **not** skip org concurrency or the org daily quota —
those are org-scoped, and the allowlist has nothing to say about an org's budget.

### 8b. Internal service identity — exempts per-IP concurrency only

The runtime calls `POST /calls/inbound` and `/calls/web` with a bot JWT whose subject
is `bot@voicera.internal` (`routers/users.py:28`). All of it originates from one
container address, so per-IP concurrency would throttle the platform against itself
under load.

That justification covers per-IP concurrency **and nothing else**. Scope the exemption
to exactly that.

This is the single easiest way to build a limiter that enforces nothing. The bot
identity is the *only* caller of `POST /calls/inbound`
(`apps/runtime/services/backend.py:92`). If the internal exemption also skipped org
concurrency and the org daily quota, then **every inbound telephony call would be
exempt from both** — rows 2 and 3 of the §1 table, silently disabled, with a green
dashboard. An org-scoped limit must never be skipped on the basis of who submitted the
request; the org is the subject, not the caller.

The bot identity must therefore not be able to reach a web call the browser did not
admit. That is Layer 2b's job: delete the runtime's self-mint fallback so the only
`/calls/web` caller is the browser, carrying a real user JWT and a real client address.
Until that lands, the internal exemption plus the self-mint path is a complete bypass.

### 8c. What is never exempt

The runtime duration cap — meaning no allowlist, org override or caller identity can
skip it while limiting is on. (`RATE_LIMIT_ENABLED=false` still disables it along with
everything else; the master switch is not an exemption.) That guard runs in the runtime
process from the agent config and has no IP context — and a telephony call has no meaningful client IP at all. Treat
`MAX_CALL_DURATION_CEILING_SECONDS` as an unconditional safety rail rather than a rate
limit. To uncap a specific org, raise its `max_call_duration_seconds` override; that is
the correct axis for it.

### Traps

**The allowlist is only meaningful if proxy trust is configured correctly.** With
`TRUST_PROXY_HEADERS=false` behind nginx, every request resolves to the proxy address.
Allowlisting `127.0.0.1` in that state exempts the entire internet. Mitigation: log a
startup **error** when the allowlist contains a loopback or RFC1918 range while
`TRUST_PROXY_HEADERS` is false.

Both exemption paths log `rate_limit.bypass scope=… reason=allowlist|internal`. A
silent bypass is indistinguishable from a limiter that has stopped working.

Changing the list requires a restart. If live edits are needed later, back it with a
small `limits_allowlist` collection reusing the `policy.py` cache — not worth building
now.

## 9. Implementation

### Layer 0 — primitives (no behaviour change)

New package `app/services/limits/`:

- `counters.py` — `incr_window(key, limit, ttl) -> (allowed, count, reset_at)`,
  `add_usage` / `get_usage`, and `claim_once(key, ttl) -> bool` (a `SET NX` used by
  Layer 2b's nonce check). Registered Lua scripts, shared Redis client.
- `policy.py` — effective-limit resolution with the 60s cache (§6).
- `errors.py` — `LimitExceeded(scope, limit, retry_after)`.
- `deps.py` — FastAPI dependency factories.

New `app/utils/client_ip.py` (§7). New settings in `app/config.py` (§6, §7, §8) plus
`RATE_LIMIT_ENABLED`, `RATE_LIMIT_FAIL_OPEN` and `RATE_LIMIT_SCOPE_STALE_SECONDS`.
Mirror all of them into `.env.example` and
`docs/developer/reference/environment-variables.md`.

Also in this layer, the cheap correctness fixes: S3, S3b, S4, S6, S7.

Exception handler mapping `LimitExceeded` → HTTP 429 with `Retry-After` and a stable
machine-readable `code`. The body carries the scope and the retry delay and nothing
about the account.

### Layer 1 — IP limits on unauthenticated endpoints

Wire dependencies into `routers/users.py`: `/signup` (attempts window before the work,
success counter after), `/login`, `/forgot-password` (plus the per-email counter),
`/reset-password`, `/check/{email}`.

### Layer 2 — unified call admission

New `app/services/call_admission.py`, one funnel, cheapest check first:

1. Exemption check (§8a/§8b — note the two have different scopes).
2. Org daily quota — reject when consumed ≥ limit, or when the remainder is under 30
   seconds. Starting a call that dies four seconds later is worse than a clean refusal.
3. Org concurrency — existing `acquire_org_slot`.
4. Per-IP concurrency — the same call with `scope_key=f"ip:{ip_hash}"`. Applied to web
   calls, where a real client address exists. Skipped for telephony, where the
   apparent address belongs to the provider webhook.

Then `bind_call_slot(slot, call_id)` once the CallLog exists, so the release path in §3
frees it on hangup. On any failure after slot acquisition: release the slot, mark the
CallLog failed. The rollback pattern at `campaign_call_dispatcher.py:212-223` is the
reference.

**Call it from the routers, not the services.** `register_web_call`
(`web_call_service.py:38`) and `register_inbound_call` are synchronous `def`s;
admission is async Redis, so it cannot be dropped inside them without converting the
whole service layer. The routers (`routers/calls.py:125`, `:148`, `:171`) are already
`async def`, and they are the only layer with the `Request` object that §7 needs to
resolve a client IP. Admission goes there; the services stay synchronous and unaware.

The campaign dispatcher keeps its own path — it needs the wait-and-retry loop — but
gains the quota check and the usage increment. The orchestrator runs as a separate
container (`docker-compose.yaml:255`) and inherits the new settings through
`env_file: .env`; verify that rather than assuming it.

### Layer 2b — authenticate the agent WebSocket (blocking, see S1/S2)

Without this layer, Layer 2 is decorative on the web-call path and §8b is a bypass.

**Flow inversion, stated explicitly.** The browser already pre-registers the call
(`createBrowserClient.ts:45`) — but swallows the failure and connects anyway
(`:48`: *"Couldn't pre-register web call, connecting without call_id"*), and the
runtime covers for it by self-minting (`agent.py:79-99`). Both halves go:

- Frontend: a failed `createWebCall` becomes **fatal**. No `call_id`, no connection.
  The 429 body's `code` drives the user-facing message.
- Runtime: delete the self-mint fallback. A web call with no `call_id` and no valid
  token closes 1008. The runtime no longer creates calls; it only joins admitted ones.

**Token.** The API mints it inside `call_admission` and returns it on the `/calls/web`
response. Payload: `org_id`, `agent_id`, `call_id`, `exp`, `nonce`. Expiry 60 seconds —
it only has to survive the round trip from the admission response to
`client.connect()`.

- **Sign with a dedicated `RUNTIME_SESSION_SECRET`, not `SECRET_KEY`.** Verification
  happens in `apps/runtime`; signing web-call tokens with the JWT signing key means a
  runtime compromise mints admin JWTs for any org. The runtime already sees the root
  `.env` through compose `env_file`, which makes this easy to get wrong by accident.
  A separate secret keeps the blast radius at "can forge a web-call admission".
- **Use stdlib `hmac` + `hashlib`, not `jose`.** `jose` is an `apps/api` dependency;
  `apps/runtime/requirements.txt` does not have it, and the runtime is where
  verification runs. An HMAC-SHA256 over a compact payload needs no library. Compare
  with `hmac.compare_digest`.
- **The nonce must actually be checked.** A signed token with an unchecked nonce is
  replayable for its whole lifetime, and since a `call_id` can be reconnected, replaying
  one admission N times bypasses per-IP concurrency entirely. The runtime calls
  `claim_once(f"ws_nonce:{nonce}", ttl)` — one `SET NX` — and rejects on a second use.
  The runtime reaches this through the API (it holds no Redis client, §5): a small
  internal endpoint authenticated with `INTERNAL_API_KEY`.

**Backend client.** `services/backend.py` distinguishes admission denial (429/403) from
transport failure, and the runtime closes 1008 on denial instead of proceeding (S2).

### Layer 3 — hard call-duration cap

New `apps/runtime/services/pipecat/duration_guard.py` — an asyncio watchdog.

Effective limit = `min(behaviour.call_timeout_seconds or MAX_CALL_DURATION_SECONDS,
MAX_CALL_DURATION_CEILING_SECONDS)`. The ceiling is applied server-side, so an org
editing its own agent config cannot escape it.

Started in `run_with_lifecycle` (`apps/runtime/services/pipecat/lifecycle.py:50`),
cancelled in the existing `finally`. On fire: log, cancel the worker so the established
finalisation path runs, and set `end_reason="max_duration"` on the finalise patch.

**`end_reason` does not exist yet and will be silently dropped if it is not added.**
There are zero occurrences of the field in the repo. Required, all three:

- `CallLogUpdateRequest` (`models/schemas.py:573-580`) — add `end_reason: Optional[str]`.
  Without it pydantic discards the field and the cap becomes invisible, which is the
  worst possible failure shape for an observability signal.
- `CallLogResponse` — add it, so the dashboard can show why a call ended.
- `finalize_call` (`lifecycle.py:30`) — take an optional `end_reason` and include it in
  the patch. It currently hardcodes `status: completed` / `call_response: answered` and
  accepts no reason.

### Layer 4 — usage accounting

The hook is **`patch_call_log`** (`call_log_service.py:84`), at the point where
duration is computed (`:101-104`) — *not* `update_call_log` (`:65`), which has no
duration logic at all and is used by the campaign dispatcher for metadata patches.

`patch_call_log` is the right single hook for three reasons:

- `patch_call_log_by_provider_sid` delegates to it (`:138`), so telephony finalisation
  is covered by the same hook.
- Its existing `_has_end_time` guard (`:96-100`) pops `duration` when `end_time_utc` is
  already set, which makes the increment **naturally idempotent**. A redelivered
  hangup webhook cannot double-count. This is the whole reason to put the increment
  here rather than in the router.
- It is the same transition — `end_time_utc` landing for the first time — that should
  also trigger a belt-and-braces `release_call_slot(call_id)`. See §10.

`INCRBY` the org's daily counter with a 48h TTL. The function is synchronous, so use a
small synchronous Redis client for the single command. Wrapped in try/except: a Redis
failure must never break call finalisation.

Known bound: the quota is checked at admission only, so the worst-case daily overshoot
is `org_concurrency × max_call_duration` — 100 minutes at the defaults. Documented and
accepted. Killing calls mid-flight to enforce a daily quota is real complexity for
little gain; revisit only if billing demands it.

## 10. Failure modes

| Condition | Behaviour | Rationale |
|---|---|---|
| Redis unreachable, `RATE_LIMIT_FAIL_OPEN=true` (default) | Allow, log `rate_limit.fail_open` at ERROR, increment a counter | A limiter outage must not take down signup and calls |
| Redis unreachable, fail-open disabled | 503 with `Retry-After` | For deployments that prefer refusal to unmetered spend |
| Malformed allowlist / missing IP salt | Startup aborts | §8a, S5 |
| Resolved IP subject cardinality is 1 | Alert | §7 — the proxy-hop misconfiguration, which presents as a platform-wide outage |
| Usage increment fails | Call finalises normally, warning logged | Accounting is not on the critical path |
| Admission denied | 429 to the API caller; 1008 close to the WebSocket | S2 |
| Slot never released | Reaped after `RATE_LIMIT_SCOPE_STALE_SECONDS` (per-IP) or `stale_call_timeout` (org) | See below |

### Slot leaks are the operational risk in this design

The release path (§3) is real but best-effort, and every link can drop it:

- `finalize_call` (`lifecycle.py:30-46`) wraps the CallLog update *and* the
  notification in one try/except. If the update throws, the notification never runs and
  the slot leaks.
- `notify_campaign_call_status` returns early and silently when `INTERNAL_API_KEY` is
  unset (`backend.py:273-275`).
- A runtime crash or container restart mid-call skips it entirely.
- A call that never got a `call_id` never finalises at all (`runners.py:70`).

Today this costs one org-concurrency slot out of ten until a 20-minute reaper. Per-IP
concurrency changes the arithmetic: a leaked slot out of five, reaped on the same
timer, is a materially worse user experience for the person who was just trying to
place a test call.

Three mitigations, all cheap, all in this plan: the shorter independent scope reaper
(S3b), the raised per-IP default (§6), and the second release trigger in
`patch_call_log` (Layer 4), which fires on the DB write rather than on the runtime's
notification and therefore survives the runtime dying after the patch lands.

Also emit `call_admission.slot_reaped` when the Lua removes a stale member, so leaks
are countable rather than inferred. A rising reap rate is the signal that one of the
four links above has broken.

### Fail-open

Fail-open is the right default for abuse limits, and it is a real cost exposure for the
daily quota. That is why the fail-open path logs at ERROR with a dedicated counter:
this is an alerting condition, not a debug line.

## 11. Accepted risks and non-goals

- **Fixed-window boundary bursts** of up to 2× the limit. Irrelevant at these limits;
  the sliding-window implementation remains available if a scope ever needs it.
- **Shared NAT.** Offices and carrier-grade NAT put many legitimate users behind one
  address. The allowlist is the escape hatch; per-IP limits are set loose enough that
  ordinary shared egress does not trip them.
- **Daily-quota overshoot** bounded by concurrency × max duration (§9, Layer 4).
- **Slot leaks** bounded by the reaper windows (§10), mitigated but not eliminated.
- **Session-token replay within its 60s window** is closed by the nonce check, but a
  token intercepted before first use is usable once. Mitigated by TLS and the short
  expiry; not otherwise addressed.
- **Knowledge-base embedding spend** (`/knowledge` uploads, `KB_EMBEDDING_API_KEY`) is
  another denial-of-wallet surface and is not covered here. The same `incr_window`
  primitive covers it in a few lines when wanted.
- **CORS (S8)** and **telephony webhook signatures (S10)** are flagged but not fixed by
  this work.
- No per-endpoint limit registry, no distributed token leasing, no admin UI.

## 12. Testing

`apps/api/tests/test_limits.py`:

- Window rollover, and that the counter expires rather than accumulating.
- Fail-open and fail-closed behaviour on a raising Redis client.
- `X-Forwarded-For` parsing: a spoofed leftmost hop must be ignored; trust disabled
  must ignore the header entirely; a two-element chain with `TRUSTED_PROXY_HOPS=2`
  resolves to the first element and with `=1` to the second (the §7 hazard, pinned).
- IPv6 addresses inside one /64 share a counter.
- Allowlist: exact address, CIDR, v6 prefix, and a malformed entry aborting startup.
- Admission rejects at quota exhaustion and with under 30 seconds remaining.
- The sixth concurrent web call from one address is refused; the second from another
  address is admitted.
- An allowlisted address skips per-IP limits but **still** hits the org daily quota and
  org concurrency (§8a).
- A request carrying the `bot@voicera.internal` subject skips per-IP concurrency but
  **still** hits the org daily quota and org concurrency (§8b). This is the regression
  test for the failure mode that silently disables the headline quotas.
- The scope zset is reaped on `RATE_LIMIT_SCOPE_STALE_SECONDS`, not on
  `stale_call_timeout` (S3b).
- `patch_call_log` increments usage once; a second patch with `end_time_utc` already
  set does not increment again (Layer 4 idempotency).

`apps/runtime` tests:

- The duration guard fires at the limit and sets `end_reason`, and `end_reason`
  survives the round trip through `CallLogUpdateRequest` rather than being dropped.
- It is cancelled cleanly on a normal hangup.
- The env ceiling clamps an oversized per-agent value.
- A missing or invalid session token closes the socket before `accept()` (S1).
- A token whose nonce has already been claimed is rejected (Layer 2b replay).
- A web call with no `call_id` closes the socket — the self-mint fallback is gone (S1).
- An admission denial closes the socket instead of running the pipeline (S2).

## 13. Rollout

1. **Layers 0 + 1, with `TRUST_PROXY_HEADERS=false`.** Limits apply per proxy address,
   which is useless but harmless, and gets the code path in production.
2. **Fixes S3, S3b, S4, S6, S7** alongside Layer 0 — small, independently reviewable.
3. **Measure the proxy chain (§7)** and only then set `TRUST_PROXY_HEADERS=true` with a
   verified `TRUSTED_PROXY_HOPS`. Confirm subject cardinality is greater than one
   before trusting any number on the denials dashboard. This step is not optional and
   cannot be done from reading the config.
4. **Layer 2b before Layer 2.** Authenticate the socket and remove the self-mint
   fallback first; otherwise Layer 2's quotas are bypassable and the rollout gives false
   assurance. This ordering is the one non-obvious sequencing constraint in the plan.
5. **Layer 2** with `RATE_LIMIT_ENABLED=false` in production first. Run the admission
   path in shadow — log the decision without acting on it — for long enough to see the
   real distribution, then enable. Use that window to pick the final
   `MAX_CONCURRENT_CALLS_PER_IP`.
6. **Layers 3 + 4 together.** A quota with no counter feeding it is not a quota.

Rough size: ~650 lines added, ~140 lines touched across 14 existing files, plus the
frontend token pass-through and the fatal-on-failure change to `connectBrowserCall`.

## 14. Observability

Structured log events, all with a hashed subject and never a raw address:

- `rate_limit.deny scope=… subject=… limit=… count=…` — INFO
- `rate_limit.bypass scope=… reason=allowlist|internal` — INFO
- `rate_limit.fail_open scope=… error=…` — ERROR, alertable
- `rate_limit.subject_resolved hops=… raw_xff=… subject=…` — INFO, first N requests
  after boot only (§7)
- `call_admission.reject reason=quota|concurrency_org|concurrency_ip org_id=…` — INFO
- `call_admission.slot_reaped scope=org|ip age=…` — INFO, alertable on rate (§10)
- `call.max_duration_reached call_id=… limit=…` — INFO

Useful first dashboard: denials per scope per hour, fail-open count (should be zero),
distinct subjects per scope per hour (must be > 1, §7), slot-reap rate (should be near
zero, §10), and daily call-seconds per org against quota.
