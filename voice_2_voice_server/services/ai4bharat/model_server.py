"""Endpoint resolution for the model-server gateway hosting IndicNemotron / Orpheus."""

import os


def model_server_url(path: str, *, websocket: bool = False) -> str:
    """Join ``path`` onto ``INDIC_MODEL_SERVER_URL`` (e.g. http://model-gateway:8000).

    A trailing ``/v1`` on the configured base is tolerated, since that is how
    OpenAI-style base URLs are usually written.
    """
    base = (os.getenv("INDIC_MODEL_SERVER_URL") or "").strip().rstrip("/")
    if not base:
        raise ValueError("INDIC_MODEL_SERVER_URL environment variable not set")
    if base.endswith("/v1"):
        base = base[:-3]
    if websocket:
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
    return base + path
