"""Azure OpenAI model catalog.

Model names here are Azure deployment names, not upstream OpenAI model IDs.
"""

LLM_MODELS: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-35-turbo",
)

DEFAULT_LLM_MODEL = "gpt-4o-mini"
