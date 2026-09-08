"""Groq LLM model catalog."""

LLM_MODELS: tuple[str, ...] = (
    "llama-3.3-70b-versatile",
    "deepseek-r1-distill-llama-70b",
    "qwen-qwq-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
)

DEFAULT_LLM_MODEL = "llama-3.3-70b-versatile"
