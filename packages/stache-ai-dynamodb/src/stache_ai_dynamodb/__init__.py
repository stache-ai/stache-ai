"""stache-ai-dynamodb - Dynamodb provider for Stache AI

This package provides dynamodb integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-dynamodb

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from decimal import Decimal
from typing import Any


# Define utility function BEFORE importing submodules that use it
# (avoids circular import)
def sanitize_for_dynamodb(obj: Any) -> Any:
    """Recursively convert Python floats to Decimal for DynamoDB compatibility.

    DynamoDB's boto3 type serializer rejects Python floats - they must be
    converted to Decimal. This function recursively processes dicts, lists,
    and scalar values.

    Args:
        obj: Any Python object (dict, list, float, int, str, bool, None)

    Returns:
        The same structure with floats converted to Decimal

    Example:
        >>> sanitize_for_dynamodb({"score": 0.95, "items": [1.5, 2.5]})
        {'score': Decimal('0.95'), 'items': [Decimal('1.5'), Decimal('2.5')]}
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: sanitize_for_dynamodb(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_dynamodb(item) for item in obj]
    else:
        return obj


# Import submodules AFTER defining sanitize_for_dynamodb
from .namespace import DynamoDBNamespaceProvider
from .document_index import DynamoDBDocumentIndex

__version__ = "0.1.0"
__all__ = ["DynamoDBNamespaceProvider", "DynamoDBDocumentIndex", "sanitize_for_dynamodb"]
