# 🤝 Contributing to VoicEra

Thanks for your interest in contributing! This file is the short version; the
full guide lives in [`docs/developer/guides/contributing-guide.md`](docs/developer/guides/contributing-guide.md).

## 🚀 Getting started

```bash
git clone https://github.com/COSS-India/VoicEra.git
cd VoicEra

make application-up
```

Use `make application-up` rather than a bare `docker compose up` — it generates the secrets
the stack requires. See [`docs/guides/quickstart/install-and-run.md`](docs/guides/quickstart/install-and-run.md).

There is no `pip install -e .`; `pyproject.toml` is a placeholder. Install per app:

```bash
pip install -r apps/api/requirements.txt
pip install -r apps/runtime/requirements.txt
```

## 🔁 Workflow

1. Open an issue first for anything substantial.
2. Branch from `dev`: `git checkout -b your-change`.
3. Make the change, with tests where behaviour changes.
4. Run the suites (below).
5. Open a pull request against `dev`.

## ✍️ Commit messages

Sentence-case imperative summary, no type prefix, no trailing period — match the
existing history:

```
Add campaign CSV upload functionality and validation
Enhance call log patching functionality and introduce new endpoint
```

## 🧪 Running the tests

There is no CI, so please run these yourself:

```bash
python -m pytest apps/api/tests
python -m pytest apps/runtime/tests
python -m pytest apps/telephony/tests
python -m pytest apps/providers/tests
cd model-server && python -m pytest tests   # no GPU needed
```

## 🎨 Code style

- Line length 100; `model-server/ruff.toml` is the lint config for that tree.
- Type hints on new code.
- Match the surrounding code: explicit registries over if/elif chains, Pydantic
  models at boundaries, small modules.

## 🔌 Extension points

Adding a provider or telephony vendor should not require touching shared code:

- [Adding an AI provider](docs/developer/guides/adding-a-provider.md)
- [Adding a telephony provider](docs/developer/guides/adding-a-telephony-provider.md)

## 📚 Documentation

Docs live in `docs/` and are built with [Mintlify](https://mintlify.com).
Navigation is defined in [`docs.json`](docs.json). The hosted docs site is
live at [voicera.mintlify.app](https://voicera.mintlify.app). If you change
behaviour, update the page that documents it.

There are three tabs: Guides, Developer, and API Reference. Add a new page to the
matching group in `docs.json`, or it will not appear in the sidebar.

Preview locally with `npx mint dev` from the repository root.

`.docs-meta/STYLE.md` is the style contract.

## 🔒 Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## 📜 Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## ⚖️ Licence

Contributions are accepted under the Apache License 2.0. See [LICENSE](LICENSE).

---

Every PR, issue, and question makes this project better — thanks for being here. 💛
