"""stache-ai-s3vectors - S3Vectors provider for Stache AI

This package provides s3vectors integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-s3vectors

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .provider import S3VectorsProvider

__version__ = "0.1.0"
__all__ = ["S3VectorsProvider"]
