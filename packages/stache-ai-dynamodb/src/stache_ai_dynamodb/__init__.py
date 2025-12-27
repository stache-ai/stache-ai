"""stache-ai-dynamodb - Dynamodb provider for Stache AI

This package provides dynamodb integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-dynamodb

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .namespace import DynamoDBNamespaceProvider
from .document_index import DynamoDBDocumentIndex

__version__ = "0.1.0"
__all__ = ["DynamoDBNamespaceProvider", "DynamoDBDocumentIndex"]
