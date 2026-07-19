"""stache-ai-redis - Redis provider for Stache AI

This package provides redis integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-redis

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .provider import RedisNamespaceProvider

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-redis")
except Exception:
    __version__ = "0.2.0"  # Fallback for development
__all__ = ["RedisNamespaceProvider"]
