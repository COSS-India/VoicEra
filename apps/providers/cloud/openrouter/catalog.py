"""OpenRouter model catalog.

OpenRouter gives access to 300+ models through a single endpoint.
The list below is curated; any OpenRouter model slug is accepted.
"""

LLM_MODELS: tuple[str, ...] = (
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat-v3-0324",
)

DEFAULT_LLM_MODEL = "openai/gpt-4.1"
BASE_URL = "https://openrouter.ai/api/v1"
