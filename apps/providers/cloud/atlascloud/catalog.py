"""Atlas Cloud LLM model catalog."""

LLM_MODELS: tuple[str, ...] = (
    "qwen/qwen3.5-flash",
    "deepseek-ai/deepseek-v4-pro",
)

DEFAULT_LLM_MODEL = "qwen/qwen3.5-flash"
BASE_URL = "https://api.atlascloud.ai/v1"
