"""Azure OpenAI model catalog.

Model names here are Azure deployment names, not upstream OpenAI model IDs.
"""

# AzureOpenAIAuth has no api_version field — this is the fixed, current
# Azure OpenAI REST API version used by every caller in this repo.
API_VERSION = "2024-02-01"

LLM_MODELS: tuple[str, ...] = ("gpt-4.1-mini",)

DEFAULT_LLM_MODEL = "gpt-4.1-mini"
