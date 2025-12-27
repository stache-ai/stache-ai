"""Provider package - Extensible provider architecture for Stache

Providers are discovered via Python entry points, allowing both built-in
and external providers to be registered in pyproject.toml.

Usage:
    from stache_ai.providers import LLMProviderFactory
    provider = LLMProviderFactory.create(settings)

External plugins can add providers by defining entry points:
    [project.entry-points."stache.llm"]
    my_provider = "my_package.provider:MyLLMProvider"
"""

from .base import (
    EmbeddingProvider,
    LLMProvider,
    VectorDBProvider,
    NamespaceProvider,
    DocumentIndexProvider
)
from .factories import (
    EmbeddingProviderFactory,
    LLMProviderFactory,
    VectorDBProviderFactory,
    S3VectorsProviderFactory,
    NamespaceProviderFactory,
    RerankerProviderFactory,
    DocumentIndexProviderFactory
)
from . import plugin_loader

# Pre-load providers at import time for eager discovery
# This ensures entry points are resolved early
plugin_loader.load_all()

__all__ = [
    # Base classes
    'EmbeddingProvider',
    'LLMProvider',
    'VectorDBProvider',
    'NamespaceProvider',
    'DocumentIndexProvider',
    # Factories
    'EmbeddingProviderFactory',
    'LLMProviderFactory',
    'VectorDBProviderFactory',
    'S3VectorsProviderFactory',
    'NamespaceProviderFactory',
    'RerankerProviderFactory',
    'DocumentIndexProviderFactory',
    # Plugin loader (for advanced usage)
    'plugin_loader',
]
