# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Report privately, either by:

- Emailing the maintainers at `SECURITY_CONTACT_EMAIL` *(TODO: replace with the
  project's real security address)*, or
- Using GitHub's private security advisory flow on this repository.

Please include:

- What the vulnerability is and which component it affects.
- Steps to reproduce, or a proof of concept.
- The impact you believe it has.
- The version, branch, or commit you tested.
- Any suggested fix.

You will receive an acknowledgement, an assessment, and notice when a fix ships.
Please allow reasonable time to respond before disclosing publicly.

## Supported versions

The project has not cut a tagged release. Security fixes land on `dev` and flow
to `main`. Track the repository for updates.

## Scope

**In scope:** the source in this repository — `apps/api`, `apps/runtime`,
`apps/providers`, `apps/telephony`, `model-server`, and the deployment scripts.

**Out of scope:** cloud AI and telephony provider vulnerabilities (report to the
vendor), third-party dependencies (report upstream, but tell us if VoicEra is
affected), model weights and their licences, and misconfiguration of your own
deployment.

## Known design characteristics

These are documented properties rather than undisclosed vulnerabilities. They do
not need reporting, but a deployment must account for them. Full detail in
[`docs/guides/deployment/security-hardening.md`](docs/guides/deployment/security-hardening.md).

- The runtime's `/answer` and `/agent/{org_id}/{agent_id}` endpoints are
  **unauthenticated** — required for telephony webhooks. Rate limit and
  allowlist them at your proxy.
- `INTERNAL_API_KEY` is a shared credential that can mint organisation-scoped
  tokens for any organisation. Treat it as a root credential.
- CORS defaults to `allow_origins=["*"]` with credentials allowed.
- `GET /users/check/{email}` is public and confirms account existence.
- The reference Docker Compose stack ships default passwords.
- An unset `SECRET_KEY` generates a temporary key rather than failing, so tokens
  do not survive a restart.
- `GET /health` returns HTTP 200 even when the database is down; probes must
  parse the response body.

## Secrets

VoicEra is self-hosted, so securing a deployment is the operator's
responsibility. Configuration lives in a single root `.env`.

- **`PROVIDER_AUTH_ENCRYPTION_KEY`** — Fernet-encrypts stored provider
  credentials. It **cannot be rotated**: losing it makes every stored credential
  permanently undecryptable. Back it up with your database backups.
- **`SECRET_KEY`** — signs JWTs, and must be identical across API replicas.
- **`INTERNAL_API_KEY`** — service-to-service credential shared by the API and
  the runtime.

Call recordings and transcripts are regulated data in most jurisdictions.
Encrypt volumes at rest and set a retention policy; nothing expires
automatically.

## Full documentation

See [`docs/legal/security.md`](docs/guides/legal/security.md) and
[`docs/guides/deployment/security-hardening.md`](docs/guides/deployment/security-hardening.md).
