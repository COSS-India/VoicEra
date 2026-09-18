"""Groq LLM model catalog."""

# OpenAI-compatible endpoint (https://api.groq.com/openai/v1) — used by any
# one-shot (non-Pipecat) caller; Pipecat's own GroqLLMService bakes its base
# URL in separately and doesn't need this constant.
BASE_URL = "https://api.groq.com/openai/v1"

LLM_MODELS: tuple[str, ...] = (
    "deepseek-r1-distill-llama-70b",
    "qwen-qwq-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
)

# llama-3.3-70b-versatile was retired from Groq (confirmed via a live 404
# against a real account) — openai/gpt-oss-120b is a currently-valid default.
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"
