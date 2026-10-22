from dataclasses import dataclass


@dataclass
class UserContext:
    """
    User context provided by the UI with every message.
    Tools read it via ToolRuntime and the LLM never sees it.
    """

    user_id: str | None = None
    lat: float | None = None
    lon: float | None = None
