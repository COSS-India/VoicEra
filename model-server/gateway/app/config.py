"""Gateway configuration.

A slot is deployed when a MODEL is named for it -- the same variable that drives
COMPOSE_PROFILES -- so the gateway and Compose can never disagree about what is
running. The upstream URL defaults to the Compose service name and only needs
setting to point at a different host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Compose service names on the internal network. Overridden by <KIND>_UPSTREAM.
_DEFAULT_URL = {
    "stt": "http://stt:8001",
    "tts": "http://tts:8002",
    "llm": "http://llm:8003",
}


def _clean(name: str) -> str:
    return (os.getenv(name) or "").strip().rstrip("/")


def _demo_path(kind: str) -> str:
    """Where this slot's model serves its demo page.

    `/demo` is the slot convention and what our own folders implement. A model
    vendored from upstream in whole may serve its page somewhere else -- the
    Nemotron server puts it at the root -- and the answer to that is one
    variable, not a patch to a file we do not own. A model folder is copied in,
    not edited; the moment we start editing, every push from upstream becomes a
    merge conflict.

    Deliberately not routed through `_clean()`: that strips a trailing slash,
    which turns "/" into "" and silently falls back to /demo -- the demo would
    404 and the variable would look ignored.
    """
    raw = (os.getenv(f"{kind.upper()}_DEMO_PATH") or "").strip()
    if not raw:
        return "/demo"
    return raw if raw.startswith("/") else "/" + raw


def _demo_assets(kind: str) -> tuple[str, ...]:
    """Root-relative path prefixes this slot's demo page loads assets from.

    Our own demo pages inline everything, so they need none. A page vendored
    from upstream may not: Nemotron's does
    `audioWorklet.addModule('/static/audio-processor.js')`, an absolute path.
    Served at /demo/stt through the gateway the page's origin is the gateway,
    so that request lands here, at a root that knows nothing about /static --
    and an AudioWorklet that fails to load is reported as "could not start the
    microphone", which reads like a browser permissions problem.

    Rewriting the page is not an option: a model folder is copied in, not
    edited. So the slot declares the prefixes that belong to it.

    Comma-separated, e.g. STT_DEMO_ASSETS=/static,/assets
    """
    raw = (os.getenv(f"{kind.upper()}_DEMO_ASSETS") or "").strip()
    if not raw:
        return ()
    prefixes = []
    for part in raw.split(","):
        cleaned = part.strip().strip("/")
        if cleaned:
            prefixes.append("/" + cleaned)
    return tuple(prefixes)


@dataclass(frozen=True)
class Upstream:
    kind: str          # "stt" | "tts" | "llm"
    url: str           # "" when the slot is not deployed
    model: str         # model id, also the Compose profile name
    demo_path: str = "/demo"   # where this model serves its page; see _demo_path
    demo_assets: tuple[str, ...] = ()   # root-relative prefixes it owns; see _demo_assets

    @property
    def enabled(self) -> bool:
        return bool(self.model and self.url)


@dataclass(frozen=True)
class Settings:
    stt: Upstream
    tts: Upstream
    llm: Upstream

    @staticmethod
    def _slot(kind: str) -> Upstream:
        model = _clean(f"{kind.upper()}_MODEL")
        url = _clean(f"{kind.upper()}_UPSTREAM") or (_DEFAULT_URL[kind] if model else "")
        return Upstream(kind, url, model, _demo_path(kind), _demo_assets(kind))

    @classmethod
    def from_env(cls) -> Settings:
        return cls(*(cls._slot(k) for k in ("stt", "tts", "llm")))

    def all(self) -> list[Upstream]:
        return [self.stt, self.tts, self.llm]


settings = Settings.from_env()
