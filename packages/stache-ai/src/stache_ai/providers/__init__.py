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

from . import plugin_loader
from .base import (
    DocumentIndexProvider,
    EmbeddingProvider,
    LLMProvider,
    NamespaceProvider,
    VectorDBProvider,
)
from .factories import (
    DocumentIndexProviderFactory,
    EmbeddingProviderFactory,
    LLMProviderFactory,
    NamespaceProviderFactory,
    RerankerProviderFactory,
    S3VectorsProviderFactory,
    VectorDBProviderFactory,
)

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
