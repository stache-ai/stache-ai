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

__version__ = "0.1.0"
__all__ = ["OllamaLLMProvider", "OllamaEmbeddingProvider", "OllamaReranker"]
