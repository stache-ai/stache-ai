"""stache-ai-mongodb - Mongodb provider for Stache AI

This package provides mongodb integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-mongodb

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .namespace import MongoDBNamespaceProvider
from .document_index import MongoDBDocumentIndex

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-mongodb")
except Exception:
    __version__ = "0.2.0"  # Fallback for development
__all__ = ["MongoDBNamespaceProvider", "MongoDBDocumentIndex"]
