from django.conf import settings
from langchain_openrouter import ChatOpenRouter

MODELS = {
    "claude-sonnet-5.5": {"label": "Claude Sonnet 5.5", "id": "anthropic/claude-sonnet-5.5"},
    "gpt-6-luna": {"label": "GPT 6 Luna", "id": "openai/gpt-6-luna"},
    "muse-spark-1.3": {"label": "Muse Spark 1.3", "id": "meta/muse-spark-1.3-contributor"},
    "mimo-v2.6": {"label": "MiMo V2.6", "id": "xiaomi/mimo-v2.6-flash"},
    "deepseek-v4.1": {"label": "DeepSeek V4.1", "id": "deepseek/deepseek-v4.1-flash-1017"},
}
THINKING_LEVELS = ["low", "medium", "high"]

DEFAULT_MODEL = "claude-sonnet-5.5"
DEFAULT_THINKING = "low"


def build_model(model_key: str = DEFAULT_MODEL, thinking: str = DEFAULT_THINKING) -> ChatOpenRouter:
    """The chat model for one agent run. Rejects anything that is not in the whitelist."""

    if model_key not in MODELS:
        raise ValueError(f"Unknown model: {model_key}")
    if thinking not in THINKING_LEVELS:
        raise ValueError(f"Unknown thinking level: {thinking}")

    return ChatOpenRouter(
        model=MODELS[model_key]["id"],
        api_key=settings.OPENROUTER_API_KEY,
        reasoning={"effort": thinking},
        max_retries=2,
    )
