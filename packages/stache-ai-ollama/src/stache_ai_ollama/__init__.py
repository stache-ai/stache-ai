"""stache-ai-ollama - Ollama provider for Stache AI

This package provides ollama integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-ollama

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .llm import OllamaLLMProvider
from .embedding import OllamaEmbeddingProvider
from .reranker import OllamaReranker

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-ollama")
except Exception:
    __version__ = "0.2.0"  # Fallback for development
__all__ = ["OllamaLLMProvider", "OllamaEmbeddingProvider", "OllamaReranker"]
