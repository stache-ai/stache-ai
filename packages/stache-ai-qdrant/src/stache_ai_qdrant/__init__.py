"""stache-ai-qdrant - Qdrant provider for Stache AI

This package provides qdrant integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-qdrant

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .provider import QdrantVectorDBProvider

__version__ = "0.1.0"
__all__ = ["QdrantVectorDBProvider"]
