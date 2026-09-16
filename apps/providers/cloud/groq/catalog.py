"""Groq LLM model catalog.

Groq gates part of its catalog behind the Enterprise plan — a gated id is
absent from a standard key's ``GET /v1/models`` and fails the request at the
first completion, which ends the pipeline mid-call. So this lists only what a
standard/developer plan can actually call (verified 2026-09-16 against
https://console.groq.com/docs/models). Enterprise ids (``llama-3.3-70b-versatile``,
``llama-3.1-8b-instant``, ``minimaxai/minimax-m2.7``) are reachable by typing
them in — the model field sets ``allow_custom_input``.

Left out on purpose:
- ``groq/compound`` / ``groq/compound-mini`` — tool-augmented systems (web
  search, code execution), billed by arrangement rather than per token.
- ``openai/gpt-oss-safeguard-20b`` — safety classifier, not a conversational model.
- ``allam-2-7b`` — Arabic/English tuned, no use on an Indic voice stack.
"""

LLM_MODELS: tuple[str, ...] = (
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
)

# Cheapest of the three ($0.075 in / $0.30 out per 1M tokens). Step up to
# openai/gpt-oss-120b when a language needs the larger model.
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"
