"""Plugin loader for Stache providers - Entry point based discovery

Discovers and loads providers from entry points for all provider types.
Both built-in providers (from stache package) and external plugins
(from third-party packages) are discovered via the same mechanism.

Entry Point Groups:
    - stache.llm: LLM providers
    - stache.embeddings: Embedding providers
    - stache.vectordb: Vector database providers
    - stache.namespace: Namespace registry providers
    - stache.reranker: Reranker providers
    - stache.document_index: Document index providers
    - stache.enrichment: Enrichment middleware
    - stache.chunk_observer: Chunk observer middleware
    - stache.query_processor: Query processor middleware
    - stache.result_processor: Result processor middleware
    - stache.delete_observer: Delete observer middleware

Usage:
    # Get all providers of a type
    providers = get_providers('llm')  # {'anthropic': AnthropicLLMProvider, ...}

    # Get a specific provider class
    provider_class = get_provider_class('llm', 'anthropic')

    # Pre-load all providers (optional, for eager loading)
    load_all()
"""

import importlib.metadata
import logging
from typing import Union

from .base import (
    DocumentIndexProvider,
    EmbeddingProvider,
    LLMProvider,
    NamespaceProvider,
    VectorDBProvider,
)
from .reranker.base import RerankerProvider

logger = logging.getLogger(__name__)

# Type alias for any provider class
ProviderType = Union[
    type[EmbeddingProvider],
    type[LLMProvider],
    type[VectorDBProvider],
    type[NamespaceProvider],
    type[DocumentIndexProvider],
    type[RerankerProvider]
]

# Entry point groups for each provider type
PROVIDER_GROUPS = {
    'llm': 'stache.llm',
    'embeddings': 'stache.embeddings',
    'vectordb': 'stache.vectordb',
    'namespace': 'stache.namespace',
    'reranker': 'stache.reranker',
    'document_index': 'stache.document_index',
    'enrichment': 'stache.enrichment',
    'chunk_observer': 'stache.chunk_observer',
    'query_processor': 'stache.query_processor',
    'result_processor': 'stache.result_processor',
    'delete_observer': 'stache.delete_observer',
}

# Cache for loaded providers: {provider_type: {name: class}}
_provider_cache: dict[str, dict[str, ProviderType]] = {}

# Track if full discovery has been performed
_loaded: bool = False


def discover_providers(group: str) -> dict[str, ProviderType]:
    """Discover providers for a specific entry point group

    Args:
        group: Entry point group name (e.g., 'stache.llm')

    Returns:
        Dictionary mapping provider names to provider classes

    Note:
        Providers with missing dependencies are silently skipped.
        This is intentional - not all providers need all dependencies.
    """
    providers = {}

    try:
        entry_points = importlib.metadata.entry_points()

        # Python 3.10+ returns SelectableGroups, 3.9 returns dict
        if hasattr(entry_points, 'select'):
            eps = entry_points.select(group=group)
        else:
            eps = entry_points.get(group, [])

        for ep in eps:
            try:
                provider_class = ep.load()
                providers[ep.name] = provider_class
                logger.debug(f"Discovered provider: {group}.{ep.name}")
            except ImportError as e:
                # Missing optional dependency - this is expected and normal
                logger.debug(f"Skipping {group}.{ep.name}: missing dependency - {e}")
            except Exception as e:
                # Unexpected error - log as warning
                logger.warning(f"Failed to load provider {group}.{ep.name}: {e}")

    except Exception as e:
        logger.warning(f"Failed to discover providers for {group}: {e}")

    return providers


def get_providers(provider_type: str) -> dict[str, ProviderType]:
    """Get all discovered providers for a type

    Args:
        provider_type: Provider type ('llm', 'embeddings', 'vectordb',
                       'namespace', 'reranker', 'document_index', 'enrichment',
                       'chunk_observer', 'query_processor', 'result_processor',
                       'delete_observer')

    Returns:
        Dictionary mapping provider names to provider classes

    Example:
        >>> providers = get_providers('llm')
        >>> print(providers.keys())
        dict_keys(['anthropic', 'bedrock', 'fallback', 'ollama', 'openai'])
    """
    # Check if we need to discover:
    # 1. Not in cache at all, OR
    # 2. In cache but with empty dict (can happen after reset() or if discovery failed)
    cached = _provider_cache.get(provider_type)
    needs_discovery = cached is None or (isinstance(cached, dict) and len(cached) == 0)

    if needs_discovery:
        group = PROVIDER_GROUPS.get(provider_type)
        if group:
            _provider_cache[provider_type] = discover_providers(group)
        else:
            logger.warning(f"Unknown provider type: {provider_type}")
            _provider_cache[provider_type] = {}

    return _provider_cache[provider_type]


def get_provider_class(provider_type: str, name: str) -> ProviderType | None:
    """Get a specific provider class

    Args:
        provider_type: Provider type ('llm', 'embeddings', etc.)
        name: Provider name ('anthropic', 'bedrock', etc.)

    Returns:
        Provider class or None if not found

    Example:
        >>> cls = get_provider_class('llm', 'anthropic')
        >>> provider = cls(settings)
    """
    providers = get_providers(provider_type)
    return providers.get(name)


def get_available_providers(provider_type: str) -> list[str]:
    """Get list of available provider names for a type

    Args:
        provider_type: Provider type

    Returns:
        List of provider names that are available (dependencies installed)
    """
    providers = get_providers(provider_type)
    return list(providers.keys())


def load_all() -> None:
    """Pre-load all provider types into cache

    Call this early in application startup for eager loading.
    This is optional - providers are loaded lazily by default.
    """
    global _loaded
    if _loaded:
        return

    logger.info("Pre-loading all provider types...")
    for provider_type in PROVIDER_GROUPS:
        providers = get_providers(provider_type)
        logger.debug(f"Loaded {len(providers)} {provider_type} providers")

    _loaded = True
    logger.info("Provider discovery complete")


def reset() -> None:
    """Reset plugin loader cache

    For testing purposes only. Clears all cached providers
    so they will be rediscovered on next access.
    """
    global _provider_cache, _loaded
    _provider_cache = {}
    _loaded = False
    logger.debug("Plugin loader cache reset")


def register_provider(provider_type: str, name: str, provider_class: ProviderType) -> None:
    """Manually register a provider

    For testing and runtime registration. Providers registered this way
    take precedence over entry point discovered providers.

    Args:
        provider_type: Provider type ('llm', 'embeddings', etc.)
        name: Provider name
        provider_class: Provider class

    Example:
        >>> register_provider('llm', 'test', MockLLMProvider)
    """
    if provider_type not in _provider_cache:
        _provider_cache[provider_type] = {}
    _provider_cache[provider_type][name] = provider_class
    logger.debug(f"Manually registered provider: {provider_type}.{name}")
