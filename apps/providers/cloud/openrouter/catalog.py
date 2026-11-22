"""OpenRouter model catalog.

OpenRouter gives access to 300+ models through a single endpoint.
The list below is curated; any OpenRouter model slug is accepted.
"""

LLM_MODELS: tuple[str, ...] = (
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.0-flash-001",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat",
)

DEFAULT_LLM_MODEL = "openai/gpt-4o"
BASE_URL = "https://openrouter.ai/api/v1"
