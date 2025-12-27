"""stache-ai-bedrock - Bedrock provider for Stache AI

This package provides bedrock integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-bedrock

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .llm import BedrockLLMProvider
from .embedding import BedrockEmbeddingProvider

__version__ = "0.1.0"
__all__ = ["BedrockLLMProvider", "BedrockEmbeddingProvider"]
