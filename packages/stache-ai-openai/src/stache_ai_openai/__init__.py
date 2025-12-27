"""stache-ai-openai - Openai provider for Stache AI

This package provides openai integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-openai

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .llm import OpenAILLMProvider
from .embedding import OpenAIEmbeddingProvider

__version__ = "0.1.0"
__all__ = ["OpenAILLMProvider", "OpenAIEmbeddingProvider"]
