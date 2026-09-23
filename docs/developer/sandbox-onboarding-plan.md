# Sandbox onboarding — implementation plan

Status: **implemented** (all four phases). This plan covers the four
sandbox-specific features that exist on the old `dev-sandbox` branch but had no
equivalent on `dev-sandbox-v2`, re-designed for the restructured repo
(`apps/api`, `apps/runtime`, `apps/providers`, `frontend`).

F2 and F1 are inert until `PLATFORM_PROVIDER_AUTH` / `SANDBOX_SEED_AGENTS` are
set. F3 and F4 are live on merge — F3 changes behaviour for existing installs
(admins can no longer read stored keys back in plaintext).

Tests: `apps/api/tests/test_platform_auth.py`,
`apps/api/tests/test_agent_seed.py`, plus additions to
`apps/api/tests/test_auth_routes.py`,
`apps/api/tests/test_configuration_routes.py` and
`apps/providers/tests/test_availability.py`.

One deviation from the plan as written: F4 also added `GET /auth/platform`
(§6.5). The integrations page builds its "connected" list from
`/auth/configured` and never reads `/configuration/*`, so without it the page
had no cheap way to know a provider was platform-supplied — the alternative was
pulling the full `/configuration/defaults` envelope on every page load.

| # | Feature | Old branch | New home |
|---|---------|-----------|----------|
| F1 | Default agents seeded for a new org | `app/config/default_agents.json` + `agent_service` | `app/seed/default_agents.json` + `app/services/agent_seed.py` |
| F2 | Platform-provided provider credentials | scattered `PLATFORM_*` env reads in bot + backend | `app/services/platform_auth.py` (one resolution choke point) |
| F3 | API keys never returned to clients | ad-hoc response stripping | always-mask `/auth/*` + internal resolve route for the runtime |
| F4 | Show what the platform already provides | hardcoded "default model" copy in the UI | `auth_source` on `/configuration/*` + `GET /configuration/defaults` |

The four are one product story: **a new sandbox org can place a call minutes
after signup, without owning a provider key, and can never read the platform's
keys.** They are listed as four features because they ship in four phases, but
F3 is a prerequisite for F2 — see §7.

Scope: `apps/api`, `apps/runtime` (one function), `apps/providers` (one
function), `frontend` (labels only). No changes to the call path, the pipeline,
telephony, campaigns, or the limits layer.

This file is intentionally not listed in `docs.json`, so it is not published to
the docs site. Move it into `docs/developer/reference/` once the work lands.

---

## 1. Goals

1. A signed-up sandbox org has working agents it can test immediately, with no
   configuration step.
2. Those agents run on platform-owned provider credentials until the org brings
   its own. Bringing your own key always wins over the platform key.
3. No human-facing API response ever contains a plaintext provider secret —
   platform-owned or org-owned, admin or member.
4. The UI can tell the three states apart: *the platform provides this*, *you
   connected this*, *this runs locally on the model-server*.

### Non-goals

- Per-org platform-key entitlements (which orgs may use platform keys). A
  deployment either sets platform keys or it doesn't; sandbox sets them, prod
  does not. Revisit only if a single deployment has to serve both.
- Metering platform-key spend separately from call usage. The limits layer
  (`ORG_DAILY_CALL_SECONDS`, org/IP concurrency, duration cap — see
  `rate-limiting-plan.md`) already bounds what an org can consume, and every
  provider call happens inside a call that layer admitted. A second meter would
  be a second source of truth for the same thing.
- Rewriting the integrations UI. F4 adds a badge and a state; it does not
  redesign the page.

---

## 2. Current state in v2

What already exists and must not be duplicated:

- **`ProviderAuth` collection** — per `(org_id, provider)`, secrets encrypted at
  rest with Fernet (`app/services/secret_crypto.py`), validated against the
  provider catalog (`app/services/provider_auth_catalog.py:62`,
  `validate_auth_payload`). This is a real improvement over the old branch and
  everything below builds on it, not beside it.
- **Masking already written** — `auth_service.mask_auth_secrets`
  (`app/services/auth_service.py:37`) exists and is applied, but only for
  non-admin callers (`routers/auth.py:37`, `_mask_for_user`). Admins and
  `super_admin`s get plaintext back from `GET /auth/{provider}`, and `POST
  /auth` echoes the key that was just stored.
- **The runtime reads secrets through the same public route.**
  `apps/runtime/services/backend.py:241` calls `GET /auth/{provider}` with a bot
  JWT minted at `ROLE_ADMIN` (`routers/users.py:94`) precisely so the masking is
  skipped. Secret delivery and the admin UI are the same endpoint today.
- **`authenticated` flag** — `apps/providers/availability.py:42` already reports
  local providers (model-server probe) as authenticated without any stored
  credential, and the wizard already filters on it
  (`frontend/src/lib/use-wizard-catalogs.ts:46`). F2 gets its UI behaviour for
  free by feeding the same flag.
- **`DEFAULT_SERVICE_PROVIDERS`** and `configuration_defaults()`
  (`apps/providers/schema.py:40,290`) — already written, with a comment saying
  it's "ready for a future `GET .../configurations/defaults` route" that was
  never added. F4 adds that route rather than inventing a parallel concept.
- **Knowledge-base embeddings already use a platform key** —
  `settings.KB_EMBEDDING_API_KEY` (`app/services/knowledge_service.py:75`). The
  old branch's "platform key fallback for knowledge base" commit has no v2
  equivalent to port; it is already the design. **Dropped from scope.**

### Gaps

| Gap | Consequence today |
|-----|-------------------|
| No platform credentials | A new org cannot make a call until it pastes a provider key. Fatal for a public sandbox. |
| Plaintext read-back for admins | Any sandbox signup is an org `super_admin`; with F2 landed, that becomes "any signup can read the platform's keys". |
| Secret delivery on a user-facing route | A leaked bot JWT yields every provider key for that org. |
| No default agents | Signup lands on an empty agents list with a provider-config wizard as the first experience. |
| No way to distinguish provided vs connected | UI says "Not configured" for things the platform already pays for. |

---

## 3. Design

One rule drives everything: **secrets resolve in exactly one function, and that
function is reachable from exactly one route, and that route is not
user-facing.**

```
                    ┌──────────────────────────────────────────┐
  browser  ───────► │ GET  /auth/{provider}        (masked)    │
  (admin)           │ POST /auth                   (masked)    │
                    │ GET  /auth/configured        (ids only)  │
                    └──────────────────────────────────────────┘
                                   │ auth_service.get_provider_auth_masked()
                                   ▼
                    ┌──────────────────────────────────────────┐
                    │  ProviderAuth (encrypted, org-owned)     │
                    └──────────────────────────────────────────┘
                                   ▲
                                   │ auth_service.get_provider_auth()
  runtime  ───────► ┌──────────────────────────────────────────┐
  (X-API-Key)       │ GET /auth/internal/{provider}?org_id=…   │
                    │   platform_auth.resolve(org_id,provider) │──► PLATFORM_PROVIDER_AUTH
                    └──────────────────────────────────────────┘        (env, never in DB)
```

Resolution order, in `platform_auth.resolve`:

1. org-owned `ProviderAuth` row → use it (BYO key always wins; the org pays)
2. else platform credential for that provider → use it
3. else `None` → 404, unchanged runtime error path

Platform credentials live in the environment and are never written to the
database. Rotation is an env change plus a restart; there is nothing to migrate,
nothing an org admin can delete, and no N-copies-of-the-same-secret problem.

---

## 4. F3 — Secrets never leave the API in plaintext

Lands **first**. On its own it is a small, self-contained hardening change; it is
also the thing that makes F2 safe to switch on.

### 4.1 Service layer — `app/services/auth_service.py`

Replace the `mask_secrets: bool` parameter with two named functions. A boolean
that decides whether a response contains plaintext secrets is exactly the
parameter you do not want a future caller to get wrong by default.

```python
def get_provider_auth(org_id: str, provider: str) -> dict[str, Any] | None:
    """Decrypted org credentials. Internal callers only — never a route response."""

def get_provider_auth_masked(org_id: str, provider: str) -> dict[str, Any] | None:
    """Same document with every secret masked. The only form a client may see."""
```

`upsert_provider_auth` returns the masked view too. There is no reason to echo a
key back to the caller that just sent it.

`list_provider_auth_for_org` (unmasked, no callers anywhere) — delete it; do not
expose it.

**The rename has a second caller.** `agent_telephony_service.py:83` calls
`get_provider_auth(org_id, provider, mask_secrets=False)` to provision telephony
applications. It moves to the unmasked `get_provider_auth(org_id, provider)` —
same behaviour, one fewer argument.

Telephony deliberately resolves **org credentials only**, with no platform
fallback: `provider_auth_catalog` merges telephony into the same provider
namespace, so a `plivo` entry in `PLATFORM_PROVIDER_AUTH` would otherwise let any
sandbox signup provision applications on the platform's telephony account and
consume its numbers. Media providers (STT/TTS/LLM) are metered by the limits
layer; telephony provisioning is not.

An earlier draft claimed this was enforced structurally, by `platform_auth.resolve`
having exactly one caller. That is not enforcement: `/auth/internal/{provider}`
accepts *any* provider id, so a telephony entry in the env would have been served
to the runtime, listed by `/auth/platform`, and reported `authenticated: true` by
`/configuration/telephony` — while `agent_telephony_service._build_config` still
read org credentials only, so agent creation would fail with "Telephony
credentials … are not configured". Config that is documented as unsupported but
silently half-works is worse than either extreme.

`platform_auth._credentials()` now **rejects telephony provider ids at startup**,
with a message naming the reason. The invariant is checked where the config is
parsed, not spread across the consumers.

### 4.2 Routes — `app/routers/auth.py`

- `GET /auth/{provider}` → `get_provider_auth_masked`, unconditionally. Drop
  `_mask_for_user`. Role still gates *writes*, not *reads of ciphertext*.
- `POST /auth` → returns the masked document.
- New, registered **before** `/{provider}` is irrelevant (two path segments, no
  conflict), but keep it adjacent for readability:

```python
@router.get("/internal/{provider}", response_model=ProviderAuthResponse)
async def resolve_auth_internal(
    provider: str,
    org_id: str = Query(..., description="Organisation the call belongs to"),
    _: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Decrypted credentials for the runtime. Org-owned first, platform fallback."""
```

Returns `{org_id, provider, auth, source}` with `source` in `{"org", "platform"}`
— useful in runtime logs when a call misbehaves, and free to compute.

`verify_api_key` (`app/auth.py:117`) already exists, already uses
`secrets.compare_digest`, and is already how `/campaign/internal/call-status`
and `/agents/by-phone/{phone}` are protected. This is the established pattern for
service-to-service, not a new one.

### 4.3 Runtime — `apps/runtime/services/backend.py:241`

`get_provider_auth` switches from bot JWT to `X-API-Key`. The 401-refresh-retry
block disappears with it — an API key does not expire — so this method gets
*shorter*:

```python
async def get_provider_auth(self, provider: str, org_id: str) -> dict[str, Any]:
    url = f"{self._base()}/auth/internal/{quote(provider, safe='')}"
    headers = {"X-API-Key": os.getenv("INTERNAL_API_KEY", ""), "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers, params={"org_id": org_id})
    ...
```

Error semantics unchanged: 404 → `BackendError("No auth stored for provider …")`.
`ai_service_factory.merge_models_with_auth:61` does not wrap this call, so the
`BackendError` propagates untouched to the handlers in `routes/agent.py`
(lines 69, 87, 93, 158, 176, 202) exactly as it does today. Nothing downstream
changes, and `apps/runtime/tests/test_ai_service_factory.py:54` — which asserts
`get_provider_auth` was awaited with `("openai", "org-1")` — keeps passing, since
the signature is unchanged.

The bot JWT keeps `ROLE_ADMIN` — it still writes call logs and metrics. This is
deliberately *not* a role-model change: the blast radius of a leaked bot token
shrinks to "can write call logs for one org" without touching any other
endpoint's authorisation.

### 4.4 Frontend — `Integrations.tsx:165-183`

The dialog currently fetches saved credentials and prefills the form
(`authValuesToForm(secrets, res.auth)`). With masking it would prefill
`****abcd`, and saving would store that string as the key.

Change: do not prefill. When `configured`, show the masked value as placeholder
text ("Current ····abcd — enter a new value to replace") and leave the input
empty.

**Upsert must merge, not replace.** An earlier draft of this section claimed
full-replace was fine because "almost every provider has a single secret field".
That is false: `bhashini` has nine secrets, `kenpath` three and `google` two,
and all three have no catalog-`required` entries — so a partial submission
validates cleanly and the `$set` silently drops every field the user did not
retype. Since clients can no longer read stored secrets, they cannot resend the
unchanged ones, which makes replace-on-update lossy by construction.

`upsert_provider_auth` therefore overlays the incoming fields on the decrypted
stored blob and validates the *merged* result, so catalog-required fields stay
enforced. Stale field names (a secret the catalog no longer lists) are dropped
before merging, and an undecryptable blob — after a
`PROVIDER_AUTH_ENCRYPTION_KEY` rotation — falls back to wholesale replacement so
the org can re-enter its credentials instead of being wedged.
`DELETE /auth/{provider}` remains the way to clear credentials.

### 4.5 Tests

`apps/api/tests/test_auth_routes.py` needs edits before it compiles: its `_get`
helper takes a `mask_secrets` kwarg (line 64) and is patched in as
`side_effect` at lines 131 and 170. The rename in §4.1 breaks both — update the
helper to drop the kwarg and always mask.

Then assert:
- admin `GET /auth/{provider}` returns a masked value (regression on the current
  behaviour — assert the old plaintext expectation is gone)
- `POST /auth` response is masked
- `GET /auth/internal/{p}` with no / wrong `X-API-Key` → 401
- `GET /auth/internal/{p}` with a valid key → plaintext, `source == "org"`

---

## 5. F2 — Platform-provided provider credentials

### 5.1 Config

One setting, in `app/config.py` next to `PROVIDER_AUTH_ENCRYPTION_KEY`:

```python
PLATFORM_PROVIDER_AUTH: str = Field(
    default="",
    description=(
        'JSON map of provider id → secret fields used when an org has not '
        'connected that provider, e.g. {"deepgram":{"api_key":"…"}}. '
        "Empty disables platform credentials entirely."
    ),
)
```

One JSON var rather than `PLATFORM_<PROVIDER>_<FIELD>` env conventions: the set
of secret field names is already defined per provider by the catalog, so a
convention would duplicate that mapping in a second place and drift from it.

Empty is the off switch. No separate `PLATFORM_AUTH_ENABLED` flag — a feature
flag whose only job is to disable a var that is already empty by default is a
flag that can only ever be set wrong.

### 5.2 `app/services/platform_auth.py` (new, ~50 lines)

```python
@lru_cache(maxsize=1)
def _credentials() -> dict[str, dict[str, Any]]:
    raw = (settings.PLATFORM_PROVIDER_AUTH or "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)                      # ValueError → startup abort
    return {p: validate_auth_payload(p, a) for p, a in parsed.items()}

def validate_config() -> None:
    """Called from lifespan; turns a bad env var into a startup failure."""

def providers() -> frozenset[str]:
    """Provider ids the platform supplies credentials for."""

def resolve(org_id: str, provider: str) -> tuple[dict[str, Any], str] | None:
    """(auth, source) with org-owned first, platform second, else None."""
```

`validate_auth_payload` is reused as-is: an unknown provider id, a non-secret
field, or a missing required secret in `PLATFORM_PROVIDER_AUTH` aborts startup
with the same message an org admin would get. The platform's own credentials get
no weaker validation than a user's. On top of that, a **telephony** provider id
aborts startup too (§4.1) — the one rule the catalog cannot express, because it
merges telephony and media into a single provider namespace.

`validate_config()` is called from `main.py`'s `lifespan`, alongside
`initialize_database()`. Fail fast, same as the limits layer's startup checks.

`lru_cache` means the JSON is parsed and validated once per process. Secrets stay
in memory only, never logged — log provider ids and field *names* (the existing
`ai_service_factory` log at `apps/runtime/services/ai_service_factory.py:63`
already logs `sorted(auth.keys())`, which is the right level of detail).

### 5.3 Wiring

Exactly one caller: `resolve_auth_internal` in `routers/auth.py` (§4.2). Nothing
else in the API needs a plaintext secret, so nothing else gets one.

`list_configured_providers` is **not** changed. `/auth/configured` means "what
has this org connected", and an org that has connected nothing should still be
able to disconnect nothing. Platform availability surfaces through
`authenticated` / `auth_source` instead (F4).

### 5.4 Rejected alternative

*Seed a `ProviderAuth` row per org at signup, filled with the platform key.*
This is what the old branch effectively did. It copies the same secret into
every org document, makes rotation a data migration, lets an org admin delete or
overwrite the platform's credential, and — combined with the current read-back —
hands the platform key to anyone who signs up. Resolution-time fallback has one
copy, one rotation point, and no way for a tenant to mutate it.

### 5.5 Tests

New `apps/api/tests/test_platform_auth.py`:
- unset → `resolve` returns `None`, behaviour identical to today
- org row present + platform set → `source == "org"` (BYO wins)
- no org row + platform set → `source == "platform"`
- malformed JSON / unknown provider / non-secret field → `validate_config`
  raises

---

## 6. F4 — Show what the platform provides

### 6.1 `apps/providers/availability.py`

`is_authenticated(provider, configured)` grows one optional argument rather than
a second function, so the existing local-provider probe stays the single source
of truth:

```python
def is_authenticated(
    provider: str,
    configured: AbstractSet[str],
    platform: AbstractSet[str] = frozenset(),
) -> bool:
```

and a companion that returns the *reason*:

```python
def auth_source(provider, configured, platform) -> str | None:
    """"local" | "org" | "platform" | None."""
```

Precedence: local → org → platform. A local provider needs no credential at all;
an org that connected its own key should see "Connected", not "Included".

### 6.2 `app/routers/configuration.py`

`_configured_ids` gains a sibling `_platform_ids()` returning
`platform_auth.providers()`. `_with_authenticated_list` /
`_with_authenticated_entry` add `auth_source` next to the existing
`authenticated`. `authenticated` keeps its exact current meaning ("selectable"),
so `use-wizard-catalogs.ts:46` needs no change — **platform-provided providers
become selectable in the agent wizard with zero frontend changes.** `auth_source`
is additive, for labels only.

One test does break: `test_configuration_routes.py:52` asserts *exact dict
equality* on a list entry —

```python
assert body["deepgram"] == {
    "provider": "deepgram", "name": "Deepgram",
    "provider_type": "cloud", "authenticated": True,
}
```

so the new key must be added there. A one-line edit, but it is the reason
"additive response field" is not automatically "no test churn".

New route, retiring the dead-code comment on `configuration_defaults()`:

```python
@router.get("/defaults")
async def configuration_defaults_route(current_user=Depends(get_current_user)):
    """Per-kind catalogs, DEFAULT_SERVICE_PROVIDERS, languages, and auth_source."""
```

This is the honest version of the old branch's "add default model info in
integrations page" — the default provider picks come from
`apps/providers/schema.py:40` instead of being retyped in TSX, so they cannot
drift from the registry.

The old branch's "add ai4bharat in default integrations" item needs no code: the
local providers (`indic_nemotron`, `indic_orpheus`) already register through
`availability.register_local` and will report `auth_source: "local"`. It is a UI
labelling question, handled below.

### 6.3 Frontend

- `catalog-types.ts` — add `auth_source?: "local" | "org" | "platform"`.
- `Integrations.tsx` — badge per state: **Included** (platform), **Connected**
  (org), **Local** (model-server), **Not configured** (none). For platform and
  local, the primary action becomes "Use my own key" instead of "Connect", and
  the card stops reading as a blocker.
- Nothing else. The wizard, phone numbers, and knowledge base all key off
  `authenticated`, which now already accounts for platform credentials.

### 6.4 `GET /auth/platform` (added during implementation)

```python
@router.get("/platform")
async def list_platform(_current_user=Depends(get_current_user)) -> list[str]:
    """Provider ids usable without the organisation connecting anything."""
```

Symmetric with `/auth/configured`: same router, same `list[str]` shape, same
"what can this org use" question. Registered **before** `/{provider}` — both are
single-segment, so the literal must win. The integrations page fetches it
alongside the catalog and the configured list, and badges those providers
**Included** with a "Use your own key" action instead of "Connect".

It returns provider ids only, never the credentials.

### 6.5 Tests

Extend `apps/api/tests/test_configuration_routes.py`: `auth_source` is `"org"`
for a stored credential, `"platform"` for a platform-supplied one, `"local"` for
a probed local provider, absent/`null` otherwise — and `authenticated` is `True`
for the first three.

---

## 7. F1 — Default agents for a new organisation

Lands **last**: the seeded agents are only useful once platform credentials (F2)
make their providers usable.

### 7.1 Templates — `apps/api/app/seed/default_agents.json`

A JSON list of `AgentCreateRequest` bodies. Not a Python literal: ops should be
able to retune a greeting or a system prompt without a code change, which is
exactly how the old branch's `default_agents.json` was used in practice.

```json
[
  {
    "name": "Support Demo",
    "agent_category": "websocket",
    "config": { "models": { "stt_config": {...}, "tts_config": {...}, "llm_config": {...} },
                "prompts": {...}, "language": {...} }
  }
]
```

Constraints:

- **`websocket` category only.** A telephony template would call
  `agent_telephony_service.provision_application` against a provider the new org
  has not connected. Enforced by a startup assertion, not left to a reviewer.
- **Two or three templates, not ten.** The sandbox goal is "click one and talk",
  not a catalogue. The old branch's larger set mostly existed to demo providers
  that F4 now surfaces directly.
- Templates must reference providers that are local or platform-supplied.
- **`knowledge_base.enabled` must be `false`.** Not a style preference: with KB
  enabled *and* an `org_id`, `_validate_knowledge_base`
  (`agent_config_validation.py:112-116`) calls
  `knowledge_service.assert_documents_ready`, which hits Mongo. A seeded agent
  cannot reference documents of an org created seconds ago anyway. Enforced by
  the same startup assertion as the category check.

### 7.2 Startup validation

Templates are parsed into `AgentCreateRequest` and run through
`validate_agent_config(config, org_id=None)` at import time, so a template that
references a provider id or language that no longer exists **fails the API's
startup**, not a user's signup. This is the main improvement over the old branch,
where the seed blob was inserted as-is and could silently drift from the provider
schema.

`org_id=None` is what keeps import-time validation free of database access — it
is the only argument that reaches the KB branch above. Seeding at signup calls
`validate_agent_config` again with the real `org_id`; with KB disabled that
branch is inert either way.

Additionally warn (do not fail) at startup when a template's providers are
neither local nor present in `platform_auth.providers()` — that combination
seeds agents nobody can run.

### 7.3 `app/services/agent_seed.py` (new, ~60 lines)

```python
def seed_default_agents(org_id: str, created_by_email: str) -> int:
    """Insert the default agents for a new org. Returns the number inserted."""
```

Synchronous, unlike `agent_service.create_agent`. `create_agent` is `async` only
because of telephony provisioning, which templates never use — so seeding needs
no event loop and can run inside the existing synchronous `sign_up_user`.

To avoid a second copy of the agent document shape, extract the document literal
from `agent_service.create_agent:170-183` into:

```python
def build_agent_document(org_id, created_by_email, payload, telephony=None) -> dict
```

`create_agent` calls it; `seed_default_agents` calls it too, then does one
`insert_many(docs, ordered=False)`. `org_name_unique` on `(org_id, name)`
(`database_init.py:108`) makes seeding naturally idempotent, so a retried signup
cannot half-seed.

Note the exception type: `insert_many` raises `BulkWriteError`, **not** the
`DuplicateKeyError` that `agent_service` catches on its single-document inserts
(`agent_service.py:188,308`). Swallow it only when every entry in
`exc.details["writeErrors"]` has `code == 11000`; anything else must re-raise, or
a genuine write failure becomes a silent empty agents list.

### 7.4 Hook point

In `user_service.sign_up_user`, immediately after
`org_service.create_organisation` and the membership insert, inside its own
`try/except`:

```python
if settings.SANDBOX_SEED_AGENTS:
    try:
        agent_seed.seed_default_agents(org_id, user_data.email)
    except Exception:
        logger.exception("Default agent seeding failed for org %s", org_id)
```

Two deliberate choices:

- **In the service, not the route.** `sign_up_user` is the only place an
  organisation is born; putting the hook there means a future second signup path
  inherits it.
- **Never fails signup.** A seeding bug must not turn into a 500 on account
  creation. The org exists, the user is logged in, the agents list is empty — a
  degraded state, not a broken one, and a loud log line.

### 7.5 Config

```python
SANDBOX_SEED_AGENTS: bool = Field(
    default=False,
    description="Seed the default demo agents into every newly created organisation",
)
```

Default off: self-hosted and production installs see no behaviour change.

### 7.6 Tests

New `apps/api/tests/test_agent_seed.py`:
- flag off → signup creates zero agents (exact current behaviour)
- flag on → signup creates N agents, all `org_id`-scoped, all `websocket`
- seeding twice → still N agents, no exception (idempotence via unique index)
- a template that fails `validate_agent_config` → raises at load, not at signup
- seeding raising → signup still returns 201

---

## 8. Rollout order

| Phase | Ships | Behaviour change for existing installs |
|-------|-------|---------------------------------------|
| 1 | F3 (§4) | **Yes** — org admins can no longer read back stored keys. Intentional. Requires the runtime and frontend changes in the same release. |
| 2 | F2 (§5) | None until `PLATFORM_PROVIDER_AUTH` is set. |
| 3 | F4 (§6) | Additive response fields; UI labels. |
| 4 | F1 (§7) | None until `SANDBOX_SEED_AGENTS=true`. |

Phases 2–4 are each inert until their env var is set, so they can land on `main`
without a sandbox-only branch. Phase 1 is the only one that changes behaviour on
merge, and it must be released as one unit: API, `apps/runtime/services/backend.py`,
and `Integrations.tsx` together, or the runtime loses its credentials and every
call fails to build services.

**F2 must not land before F3.** Platform credentials plus the current admin
read-back means any sandbox signup can `POST /users/signup` → `GET
/auth/{provider}` → walk away with the platform's provider keys.

---

## 9. Risks

- **Phase 1 release coupling** (above). Mitigation: single PR covering all three
  surfaces; `test_auth_routes.py` asserts both the masked route and the internal
  route.
- **`INTERNAL_API_KEY` becomes higher-value.** It already mints org-scoped bot
  JWTs (`/users/bot/token`), so it was already the most sensitive secret in the
  deployment; it now also unlocks provider credentials. No new class of exposure,
  but worth stating: it must be a distinct random value per deployment and must
  not be handed to anything that isn't the runtime.
- **Platform key exhaustion.** A sandbox burning the platform's provider quota
  is bounded by the limits layer, not by this work. If `RATE_LIMIT_ENABLED` is
  `false` when platform keys are set, the sandbox is uncapped. Call it out in the
  deployment runbook: **platform credentials and `RATE_LIMIT_ENABLED=true` ship
  together.**
- **Template drift.** Handled by §7.2 startup validation.

---

## 10. New environment variables

```bash
# Platform-provided provider credentials (F2). Empty = feature off.
# JSON: provider id → secret fields, validated against the provider catalog.
PLATFORM_PROVIDER_AUTH=

# Seed default demo agents into every newly created organisation (F1).
SANDBOX_SEED_AGENTS=False
```

Add to `.env.example` and `docs/developer/reference/environment-variables.md`.
Sandbox deployments set both, plus `RATE_LIMIT_ENABLED=true` (§9).

---

## 11. Estimated diff

| Area | Files | Rough size |
|------|-------|-----------|
| F3 | `auth_service.py`, `routers/auth.py`, `agent_telephony_service.py` (1 line), `runtime/services/backend.py`, `Integrations.tsx`, tests | ~120 lines, net −20 in the runtime |
| F2 | `config.py`, `services/platform_auth.py` (new), `main.py`, tests | ~110 lines |
| F4 | `availability.py`, `routers/configuration.py`, `catalog-types.ts`, `Integrations.tsx`, tests | ~90 lines |
| F1 | `seed/default_agents.json` (new), `services/agent_seed.py` (new), `agent_service.py` (extract), `user_service.py`, `config.py`, tests | ~180 lines |

No new dependencies, no new collections, no new infrastructure.
