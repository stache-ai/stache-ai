"""Null LLM provider for MCP-only deployments without synthesis"""

from stache_ai.config import Settings
from stache_ai.providers.base import LLMProvider


class NoneLLMProvider(LLMProvider):
    """Null LLM provider that raises error if synthesis is requested

    Use this for MCP-only deployments where synthesis is not needed.
    No credentials or external dependencies required.
    """

    def __init__(self, settings: Settings):
        """Initialize none provider (no configuration needed)"""
        pass

    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError(
            "LLM generation is not available (llm_provider='none'). "
            "To use LLM features, configure an LLM provider (bedrock, ollama, etc.) "
            "or use the fallback provider for local development."
        )

    def generate_with_context(self, query: str, context: list[dict]) -> str:
        raise NotImplementedError(
            "LLM synthesis is not available (llm_provider='none'). "
            "To use synthesis, configure an LLM provider (bedrock, ollama, etc.) "
            "or use the fallback provider for local development."
        )

    def generate_with_context_and_model(
        self, query: str, context: list[dict], model: str
    ) -> str:
        raise NotImplementedError(
            "LLM synthesis is not available (llm_provider='none'). "
            "To use synthesis, configure an LLM provider (bedrock, ollama, etc.) "
            "or use the fallback provider for local development."
        )

    def get_name(self) -> str:
        return "none"

    def get_available_models(self) -> list:
        """No models available - synthesis disabled"""
        return []

    def get_default_model(self) -> str | None:
        """No default model - synthesis disabled"""
        return None
