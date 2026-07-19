"""stache-ai-cohere - Cohere provider for Stache AI

This package provides cohere integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-cohere

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .embedding import CohereEmbeddingProvider
from .reranker import CohereReranker

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-cohere")
except Exception:
    __version__ = "0.2.0"  # Fallback for development
__all__ = ["CohereEmbeddingProvider", "CohereReranker"]
