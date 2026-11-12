---
title: Contributing
description: How to propose changes to VoicEra.
---

Contributions are welcome. This page covers the workflow; [Local setup](local-setup) covers getting the code running.

## Before you start

* Open an issue first for anything substantial. A design discussion is cheaper than a rejected pull request.
* Read [Repository layout](repository-layout) so your change lands in the right package.
* Adding a provider or a telephony vendor? Follow [Adding an AI provider](adding-a-provider) or [Adding a telephony provider](adding-a-telephony-provider) — both are designed as extension points, so you should not need to touch shared code.

## Setting up

```bash
git clone https://github.com/COSS-India/VoicEra.git
cd VoicEra
make application-up
```

`make application-up` wraps `./scripts/start-application-services.sh`; `make help` lists every target.

There is **no** `pip install -e .` — `pyproject.toml` is an empty placeholder. Install per app:

```bash
pip install -r apps/api/requirements.txt
pip install -r apps/runtime/requirements.txt
```

## Branching

Branch from `dev`, not `main`:

```bash
git checkout dev
git pull
git checkout -b your-change
```

Use a short descriptive name. Existing branches follow patterns like `dev-<feature>` and `chore/<task>`.

## Commit messages

Match the existing history: a sentence-case imperative summary, no type prefix, no trailing period.

```text
Add campaign CSV upload functionality and validation
Enhance call log patching functionality and introduce new endpoint
Standardise both STT models on /v1/realtime; detect MPS rather than assume it
```

Add a body when the reason is not obvious from the diff. Keep the summary under about 72 characters.

## Code style

| Rule | Value |
| --- | --- |
| Line length | 100 |
| Target Python | 3.12 (`model-server`); the apps run on 3.11+ |
| Type hints | Expected on new code; the codebase uses `from __future__ import annotations` |
| Docstrings | One line on modules and public functions |

`model-server/ruff.toml` is the lint configuration for that tree. It deliberately excludes vendored upstream model code — restyling somebody else's project turns every upstream sync into a merge conflict — but everything authored here is linted.

```bash
cd model-server && ruff check .
```

Match the surrounding code. The repository favours explicit registries over if/elif chains, Pydantic models at boundaries, and small modules over large ones.

## Run the checks

Run them before opening a pull request:

```bash
python -m pytest apps/api/tests
python -m pytest apps/runtime/tests
python -m pytest apps/telephony/tests
python -m pytest apps/providers/tests
(cd model-server && python -m pytest tests)
(cd frontend && npm test)
```

The model-server suite needs no GPU. See [Testing](testing) for what each suite protects.

CI runs on your pull request too — `.github/workflows/quality.yml` and `standards.yml`. These checks **fail the run** when they fail — and block the merge wherever branch protection marks them as required:

* The five Python suites, each in its own job, with a few known-failing tests deselected.
* `ruff check apps model-server --select E9,F63,F7,F82` — syntax errors and undefined names only.
* The dashboard's `npx tsc --noEmit` and `npm test`.
* The OpenAPI spec generated from the API, validated and Spectral-linted.
* hadolint errors in any Dockerfile, and `docker compose config` on `docker-compose.yaml`.

The full ruff rule set, ESLint, Bandit, Trivy, the BCP 47 language-code check, and the licence inventory only report. See [Testing → Continuous integration](testing#continuous-integration) for the full table and how to reproduce each check.

## Opening a pull request

Target `dev`. The description is pre-filled from `.github/pull_request_template.md`; in it, cover:

* What changed and why.
* Which suites you ran, and their result.
* Anything you deliberately left out.
* For behaviour changes, how a reviewer can reproduce it.

Dependabot opens version-update pull requests against `staging`, not `dev`, for pip, npm, Docker base images, and GitHub Actions (`.github/dependabot.yml`). GitHub reads that file only from the default branch, so it takes effect once it is on `main`. Dependabot security-fix pull requests are switched on separately in the repository settings and target `main`.

Keep pull requests focused — one concern each. A refactor bundled with a feature is hard to review and harder to revert.

## Documentation

Documentation lives in `docs/` and is built with Mintlify. Navigation is defined in `docs.json` at the repository root. A hosted docs site is not live yet — until it is, read the Markdown in the repo. If your change alters behaviour, update the page that describes it — a feature with stale docs is a feature people cannot use.

`.docs-meta/STYLE.md` is the style contract: front matter, callout and tab usage, mermaid conventions, naming, and the rule that every value must come from the source rather than from memory.

New page? Add it to the matching tab and group in `docs.json`, or Mintlify will not show it. Preview with `npx mint dev` from the repository root.

## Reporting security issues

Do **not** open a public issue for a vulnerability. Follow the [Security policy](../../guides/legal/security).

## Code of conduct

Participation is governed by the [Code of conduct](../../guides/legal/code-of-conduct). Be respectful, assume good faith, and keep criticism on the work.

## Licence

Contributions are accepted under the Apache License 2.0. By opening a pull request you agree your contribution may be distributed under it. See [License](../../guides/legal/license-info).

## Related

* [Local setup](local-setup)
* [Testing](testing)
* [Repository layout](repository-layout)
