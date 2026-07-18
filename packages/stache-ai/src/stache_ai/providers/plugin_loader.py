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
    - stache.post_ingest: Post-ingest processor middleware (canonical name;
      the legacy ``stache.postingest_processor`` group is still discovered as
      a back-compat alias)
    - stache.principal_extractor: Principal extractors (caller identity)
    - stache.authorizer: Authorization providers (operation-level policy)
    - stache.loader: Document format loaders
    - stache.chunking: Chunking strategies

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
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from stache_ai.loaders.base import DocumentLoader
    from stache_ai.chunking.base import ChunkingStrategy

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
    type["EmbeddingProvider"],
    type["LLMProvider"],
    type["VectorDBProvider"],
    type["NamespaceProvider"],
    type["DocumentIndexProvider"],
    type["RerankerProvider"],
    type["DocumentLoader"],
    type["ChunkingStrategy"],
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
    'postingest_processor': 'stache.post_ingest',
    'ingest_guard': 'stache.ingest_guard',  # NEW
    'error_processor': 'stache.error_processor',  # NEW
    'ingest_queue': 'stache.ingest_queue',
    'ingest_jobstore': 'stache.ingest_jobstore',
    'ingest_blob': 'stache.ingest_blob',
    'ingest_intake': 'stache.ingest_intake',
    'ingest_notifier': 'stache.ingest_notifier',
    'principal_extractor': 'stache.principal_extractor',
    'authorizer': 'stache.authorizer',
    'loader': 'stache.loader',
    'chunking': 'stache.chunking',
}

# Groups whose provider is chosen by a config NAME and whose consumer fails
# CLOSED when that name is absent: the provider factories re-raise the recorded
# cause via get_load_failures, and build_authorizer / build_principal_extractor
# refuse to fall back. For these, a broken UNCONFIGURED plugin is recorded and
# skipped rather than aborting startup. Every group NOT listed here (the
# middleware groups) keeps the strict discovery hard-fail: middleware runs as a
# discovered set with no name check, so a silently-dropped isolation middleware
# would fail OPEN. Default is strict -- a new group must be added here
# deliberately, only once it has a fail-closed name check.
_NAME_SELECTED_GROUPS = frozenset({
    'stache.llm', 'stache.embeddings', 'stache.vectordb', 'stache.namespace',
    'stache.reranker', 'stache.document_index', 'stache.ingest_queue',
    'stache.ingest_jobstore', 'stache.ingest_blob', 'stache.ingest_intake',
    'stache.ingest_notifier', 'stache.loader', 'stache.chunking',
    'stache.principal_extractor', 'stache.authorizer',
})

# Back-compat aliases: a provider type historically discoverable under a
# second entry-point group name. Both the canonical group (PROVIDER_GROUPS)
# and every alias are discovered and merged; the canonical name wins on a
# name collision. Post-ingest processors were declared under two names
# (``stache.post_ingest`` in the middleware guide/discovery registry vs
# ``stache.postingest_processor`` in the loader) — a plugin registered under
# the documented name previously would not load. The canonical name is now
# ``stache.post_ingest``; the old one stays as an alias so already-published
# plugins keep working.
GROUP_ALIASES: dict[str, list[str]] = {
    'postingest_processor': ['stache.postingest_processor'],
}

# Cache for loaded providers: {provider_type: {name: class}}
_provider_cache: dict[str, dict[str, ProviderType]] = {}

# Import failures recorded during discovery: {entry point group: {name: exc}}
#
# Tolerating an ImportError during discovery is deliberate (a provider with an
# uninstalled optional dependency must not take down the providers next to it),
# but forgetting about it is not: a provider that failed to import is NOT an
# unknown provider, and a caller who explicitly asks for it by name deserves the
# real reason rather than "Unknown provider: ...". Factories consult this map to
# tell those two cases apart.
_load_failures: dict[str, dict[str, Exception]] = {}

# Track if full discovery has been performed
_loaded: bool = False


def _entry_point_groups(group_or_type: str) -> list[str]:
    """Resolve a provider type ('llm') or entry point group ('stache.llm')

    Returns every entry point group the name maps to, aliases included.
    An unrecognised name is passed through unchanged so callers can query a
    raw entry point group directly.
    """
    if group_or_type in PROVIDER_GROUPS:
        groups = list(GROUP_ALIASES.get(group_or_type, []))
        groups.append(PROVIDER_GROUPS[group_or_type])
        return groups
    return [group_or_type]


def discover_providers(group: str) -> dict[str, ProviderType]:
    """Discover providers for a specific entry point group

    Args:
        group: Entry point group name (e.g., 'stache.llm')

    Returns:
        Dictionary mapping provider names to provider classes

    Note:
        Providers whose import fails are skipped rather than aborting discovery
        for the whole group - not every provider's optional dependencies are
        installed everywhere. The failure is logged at WARNING and recorded in
        ``_load_failures`` so ``get_load_failures()`` (and the factories) can
        report the real cause if that provider is later asked for by name.
    """
    providers = {}
    failures: dict[str, Exception] = {}

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
                # A dependency the provider needs is not importable. Usually an
                # uninstalled optional extra -- but it is also exactly what a
                # version-skewed install looks like, and that one is a real
                # outage. WARNING, not DEBUG: this has to be visible at the
                # log level things actually run at.
                failures[ep.name] = e
                logger.warning(
                    f"Provider {group}.{ep.name} failed to load and will not be "
                    f"available: {type(e).__name__}: {e}"
                )
            except Exception as e:
                if group in _NAME_SELECTED_GROUPS:
                    # This group's provider is chosen by a config NAME, and its
                    # consumer fails closed if that name is absent (the factory
                    # re-raises via get_load_failures; build_authorizer /
                    # build_principal_extractor refuse to fall back). So a broken
                    # UNCONFIGURED plugin here must NOT brick startup for the
                    # providers that work -- record it and skip. The configured
                    # one still fails loud, with the real cause.
                    failures[ep.name] = e
                    logger.warning(
                        f"Provider {group}.{ep.name} failed to load and will not "
                        f"be available: {type(e).__name__}: {e}"
                    )
                else:
                    # A middleware group: middleware runs as a discovered SET
                    # with no name selection, so a silently-vanished plugin is
                    # never noticed -- and a dropped isolation/result-filter
                    # middleware fails OPEN. Keep the hard fail; installing a
                    # broken one is a real, must-surface problem.
                    raise RuntimeError(
                        f"Installed middleware {group}.{ep.name} failed to load: {e}"
                    ) from e

    except RuntimeError:
        raise   # fail-closed: broken installed middleware (raised above)
    except Exception as e:
        logger.warning(f"Failed to discover providers for {group}: {e}")

    # Replace (not merge) this group's record: discovery just re-ran.
    _load_failures[group] = failures

    return providers


def get_load_failures(group_or_type: str) -> dict[str, Exception]:
    """Import failures recorded while discovering a provider group

    Args:
        group_or_type: Provider type ('embeddings') or entry point group
                       ('stache.embeddings')

    Returns:
        {provider name: the exception its import raised}. Empty if everything
        registered under the group imported cleanly (or discovery has not run).

    Example:
        >>> get_load_failures('embeddings')
        {'acme': ModuleNotFoundError("No module named 'acme_sdk'")}
    """
    # Make the helper usable on its own: asking about a provider type before
    # anything has resolved one should still tell you the truth.
    if group_or_type in PROVIDER_GROUPS:
        get_providers(group_or_type)

    merged: dict[str, Exception] = {}
    for group in _entry_point_groups(group_or_type):
        merged.update(_load_failures.get(group, {}))
    return merged


def get_providers(provider_type: str) -> dict[str, ProviderType]:
    """Get all discovered providers for a type

    Args:
        provider_type: Provider type ('llm', 'embeddings', 'vectordb',
                       'namespace', 'reranker', 'document_index', 'enrichment',
                       'chunk_observer', 'query_processor', 'result_processor',
                       'delete_observer', 'loader', 'chunking')

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
            merged: dict[str, ProviderType] = {}
            # Discover alias groups first, then the canonical group last so a
            # canonical registration wins on any name collision.
            for alias_group in GROUP_ALIASES.get(provider_type, []):
                merged.update(discover_providers(alias_group))
            merged.update(discover_providers(group))
            _provider_cache[provider_type] = merged
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

    For testing purposes only. Clears all cached providers (and the recorded
    import failures) so they will be rediscovered on next access.
    """
    global _provider_cache, _loaded, _load_failures
    _provider_cache = {}
    _load_failures = {}
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
