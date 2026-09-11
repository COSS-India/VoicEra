---
title: Running the dashboard
description: Run the dashboard against a local VoicEra stack.
---

`make application-up` starts the dashboard with the rest of the stack — nothing extra to do. This page covers that, and running it outside Compose when you are working on the frontend itself.

## With the stack

```bash
make application-up
```

The `frontend` service builds from `frontend/Dockerfile` and comes up on `http://localhost:3000`, wired to the API and runtime by Compose. Override the published port with `FRONTEND_HOST_PORT` in the root `.env`.

The dashboard is useless without an API to talk to — its first action after sign-in is `GET /users/me`, and it redirects to the sign-in page if that fails. Compose already orders it after `api`.

## Outside Compose

Run it directly when you are iterating on the frontend and want the Next.js dev server on your host rather than in a container. Bring the rest of the stack up first ([Install and run](../../guides/quickstart/install-and-run)), then stop the container so the port is free:

```bash
docker compose stop frontend
cd frontend
```

## Install

```bash
npm install
```

`frontend/package.json` declares no `engines` field, so no Node version is pinned there. Next.js 16 is the binding constraint in practice — use an actively supported Node LTS release. If `npm install` or `next dev` fails on a version complaint, the error names the version Next requires.

## Configure

By default there is nothing to configure. `frontend/next.config.ts` proxies every `/api/v1/*` request the browser makes to `http://127.0.0.1:8000` server-side — a Next rewrite, not CORS — so running the API on its default port is enough.

| Variable | Read in | Default | What it is |
| --- | --- | --- | --- |
| `API_PROXY_TARGET` | `frontend/next.config.ts` | `http://127.0.0.1:8000` | Where the Next server forwards `/api/v1/*`. Set this, not `NEXT_PUBLIC_API_URL`, if your API runs on a different host or port. |
| `NEXT_PUBLIC_API_URL` | `frontend/src/lib/api/http.ts` | `/api/v1` | Base path the browser calls. Leave it alone to go through the proxy; only override it (to an absolute URL) if the browser should call the API directly instead. |
| `RUNTIME_PROXY_TARGET` | `frontend/next.config.ts` | `http://127.0.0.1:7860` | Where the Next server forwards `/agent/:orgId/:agentId` WebSockets for browser test calls. Compose sets `http://runtime:7860`. |

There are no other environment variables anywhere under `frontend/`, and no `.env.example` is committed (`.env*` is gitignored).

If your API is on `localhost:8000` and the runtime is on `localhost:7860`, the defaults are enough — both REST and the test-call WebSocket go through Next rewrites. Otherwise create `frontend/.env.local`:

```bash
API_PROXY_TARGET=http://localhost:8000
RUNTIME_PROXY_TARGET=http://localhost:7860
```

`API_PROXY_TARGET` and `RUNTIME_PROXY_TARGET` are read by the Next server, so changing them needs a restart of `next dev` (or a rebuild for `next start`). `NEXT_PUBLIC_*` values are inlined into the browser bundle at build time instead — they are not secrets, but changing one needs a restart of `next dev` (or a rebuild) to take effect.

## Run

```bash
npm run dev
```

The dashboard comes up on `http://localhost:3000`. The available scripts are exactly the `create-next-app` defaults:

| Script | Command |
| --- | --- |
| `npm run dev` | `next dev` |
| `npm run build` | `next build` |
| `npm run start` | `next start` — serves a prior `build` |
| `npm run lint` | `eslint` |

Open `http://localhost:3000`. You land on the sign-in page. If you have not created an account yet, use the signup link — signup creates the organisation and its first `super_admin`, the same as `POST /users/signup`.

## Pointing at a local stack

Ports must match what the Compose stack actually published. Check them against [Ports and defaults](../reference/ports-and-defaults), and against your `.env` if you overrode `RUNTIME_HOST_PORT` or the API port.

```bash
# API reachable?
curl -s http://localhost:8000/api/v1/languages | head -c 200

# Runtime reachable?
curl -s http://localhost:7860/health
```

If the API responds directly but the dashboard still shows an error banner, open the browser devtools network tab: requests go to `/api/v1/...` on `localhost:3000`, not to the API's own port, because Next proxies them server-side — a failing request there tells you whether `API_PROXY_TARGET` points at the wrong host or the token expired.

On a `401` from any request, `apiFetch` clears the stored session and hard-redirects to `/`. A sudden bounce back to the sign-in screen means your token was rejected, not that the page crashed.

### CORS

You do not need it. The browser only ever calls same-origin `/api/v1/...`; Next's rewrite forwards that to the API server-side, so the request the API actually receives is not cross-origin. `apps/api/app/main.py` still sets `allow_origins=["*"]`, but that matters only if you set `NEXT_PUBLIC_API_URL` to an absolute URL and bypass the proxy — see [Security hardening](../../guides/deployment/security-hardening) before doing that anywhere but your own machine.

## The Compose service

`frontend` builds from `frontend/Dockerfile` (`node:24-slim`, `npm ci`, then `npm run build`). Its command is `npm run start` — a real production build, not the dev server, and there is no source bind-mount, unlike `api`.

| Setting | Value |
| --- | --- |
| Container | `voicera_oss_frontend` |
| Published port | `${FRONTEND_HOST_PORT:-3000}` → 3000 |
| `NEXT_PUBLIC_API_URL` | defaults to `/api/v1` — same-origin, not the API's own host |
| `API_PROXY_TARGET` | defaults to `http://api:8000` — where Next forwards `/api/v1/*` server-side |
| `RUNTIME_PROXY_TARGET` | defaults to `http://runtime:7860` — where Next forwards `/agent/...` WebSockets |
| Depends on | `api` (service_started) |

The proxy is the same mechanism as **Outside Compose** above, just pointed at different targets — `API_PROXY_TARGET` / `RUNTIME_PROXY_TARGET` are `127.0.0.1` there and Compose service DNS here. Either way the browser only ever addresses `/api/v1/...` and `/agent/...` on the dashboard's own origin. See [Environment variables](../reference/environment-variables#dashboard) for the full picture.

The API's own reference to the dashboard is `FRONTEND_URL` (default `http://localhost:3000`), used to build password-reset links in `apps/api/app/services/user_service.py`. Every dashboard feature remains reachable over the API, so the stack still runs headless if you remove the service.

## Related

* [Overview](overview)
* [Dashboard tour](dashboard-tour)
* [Install and run](../../guides/quickstart/install-and-run)
* [Environment variables](../reference/environment-variables)
