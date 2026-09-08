"""AWS Bedrock LLM model catalog.

Model IDs include the region inference-profile prefix (e.g. 'us.').
"""

LLM_MODELS: tuple[str, ...] = (
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)

DEFAULT_LLM_MODEL = "us.amazon.nova-pro-v1:0"
DEFAULT_AWS_REGION = "us-east-1"
