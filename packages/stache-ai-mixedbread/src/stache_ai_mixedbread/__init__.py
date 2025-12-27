"""stache-ai-mixedbread - Mixedbread provider for Stache AI

This package provides mixedbread integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-mixedbread

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .provider import MixedbreadEmbeddingProvider

__version__ = "0.1.0"
__all__ = ["MixedbreadEmbeddingProvider"]
