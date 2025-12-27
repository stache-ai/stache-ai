"""Reranker providers - Discovered via entry points

Providers in this package are registered via pyproject.toml entry points
in the 'stache.reranker' group. No manual registration needed.

The base class is still exported for type hints and inheritance.
"""

from .base import RerankerProvider

__all__ = ["RerankerProvider"]
