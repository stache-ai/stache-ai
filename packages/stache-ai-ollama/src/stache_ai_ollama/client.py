"""Ollama client with connection pooling and circuit breaker support.

This module provides an HTTP client for Ollama operations with:

1. **Resource Efficiency**: HTTP connection pooling with configurable limits
2. **Thread Safety**: Uses HttpClientFactory for consistent instance management
3. **Circuit Breaker Integration**: Automatic failure detection and recovery
4. **Automatic Retry**: Retry logic with exponential backoff handled by HttpClient
5. **Configuration from Settings**: All timeouts and pool settings from pydantic Settings

Architecture:
    OllamaClient (this module)
        └─ Wraps HttpClient from HttpClientFactory
        └─ Delegates HTTP operations to underlying client
        └─ HttpClient provides automatic retry and circuit breaker protection

Usage:
    # Create a new client instance
    client = OllamaClient(settings)

    # Use client methods (retry is automatic)
    response = client.post("/api/embeddings", {"model": "...", "input": "..."})

Thread Safety:
    Thread-safe through HttpClientFactory's double-checked locking pattern.
    Each OllamaClient instance gets the same shared HttpClient from the factory.

See: stache_ai/providers/resilience/http_client.py for HttpClientFactory implementation.
"""

from typing import Optional
import httpx
import logging
from datetime import datetime, timedelta
from stache_ai.config import Settings
from stache_ai.providers.resilience import HttpClientFactory, HttpClientConfig

logger = logging.getLogger(__name__)


class OllamaClient:
    """HTTP client wrapper for Ollama with circuit breaker support.

    Wraps an HttpClient from HttpClientFactory to provide backward-compatible
    interface for Ollama operations (embeddings, LLM, reranking). Each instance
    delegates to the shared HttpClient cached by the factory, ensuring:

    - Single connection pool per provider
    - Thread-safe instance management via factory
    - Circuit breaker protection for automatic failure recovery
    - Automatic retry with exponential backoff (handled by HttpClient)
    """

    def __init__(self, settings: Settings):
        """Initialize OllamaClient with configuration from Settings.

        Creates or retrieves a shared HttpClient from HttpClientFactory,
        which manages connection pooling and circuit breaker state.

        Args:
            settings: Pydantic Settings instance with Ollama configuration

        Raises:
            ValueError: If settings contain invalid configuration
        """
        try:
            # Extract configuration from settings
            base_url = settings.ollama_url.rstrip("/")
            default_timeout = settings.ollama_embedding_timeout
            llm_timeout = settings.ollama_llm_timeout
            health_timeout = settings.ollama_health_check_timeout

            max_connections = settings.ollama_max_connections
            max_keepalive_connections = settings.ollama_max_keepalive_connections
            keepalive_expiry = settings.ollama_keepalive_expiry

            # Retry configuration
            max_retries = settings.ollama_max_retries
            retry_base_delay = settings.ollama_retry_base_delay
            retry_max_delay = settings.ollama_retry_max_delay

            # Circuit breaker configuration
            cb_threshold = settings.ollama_circuit_breaker_threshold
            cb_timeout = settings.ollama_circuit_breaker_timeout
            cb_half_open_max = settings.ollama_circuit_breaker_half_open_max_calls

            # Store configuration for API compatibility
            self.base_url = base_url
            self.default_timeout = default_timeout
            self.llm_timeout = llm_timeout
            self.health_timeout = health_timeout
            self.max_connections = max_connections
            self.max_keepalive_connections = max_keepalive_connections
            self.keepalive_expiry = keepalive_expiry
            self.max_retries = max_retries
            self.retry_base_delay = retry_base_delay
            self.retry_max_delay = retry_max_delay

            # Create HttpClientConfig from Settings
            http_config = HttpClientConfig(
                base_url=base_url,
                headers={},  # No special headers needed for Ollama
                default_timeout=default_timeout,
                connect_timeout=10.0,
                write_timeout=10.0,
                pool_timeout=5.0,
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
                keepalive_expiry=keepalive_expiry,
                max_retries=max_retries,
                retry_base_delay=retry_base_delay,
                retry_max_delay=retry_max_delay,
                circuit_breaker_threshold=cb_threshold,
                circuit_breaker_timeout=cb_timeout,
                circuit_breaker_half_open_max_calls=cb_half_open_max
            )

            # Get shared HttpClient from factory
            self._client = HttpClientFactory.get_client("ollama", http_config)
            self.circuit_breaker = self._client.circuit_breaker

            # Health check cache (5 second TTL)
            self._health_cache: Optional[bool] = None
            self._health_cache_time: Optional[datetime] = None
            self._health_cache_ttl = timedelta(seconds=5)

            logger.info(
                f"OllamaClient initialized successfully. "
                f"Base URL: {self.base_url}, "
                f"Default timeout: {self.default_timeout}s, "
                f"LLM timeout: {self.llm_timeout}s, "
                f"Health timeout: {self.health_timeout}s, "
                f"Max connections: {self.max_connections}, "
                f"Max keepalive: {self.max_keepalive_connections}"
            )

        except Exception as e:
            logger.error(f"OllamaClient initialization failed: {e}", exc_info=True)
            raise

    def post(self, endpoint: str, json: dict, timeout: Optional[float] = None) -> httpx.Response:
        """Make POST request to Ollama API.

        Args:
            endpoint: API endpoint (e.g., "/api/embeddings")
            json: JSON payload to send in request body
            timeout: Optional timeout override in seconds (uses default_timeout if None)

        Returns:
            httpx.Response object containing the API response

        Raises:
            httpx.HTTPError: On network errors, HTTP errors, or timeout
        """
        logger.debug(f"POST {endpoint} with timeout={timeout}s")
        return self._client.post(endpoint, json=json, timeout=timeout)

    def get(self, endpoint: str, timeout: Optional[float] = None) -> httpx.Response:
        """Make GET request to Ollama API.

        Args:
            endpoint: API endpoint (e.g., "/api/version")
            timeout: Optional timeout override in seconds (uses default_timeout if None)

        Returns:
            httpx.Response object containing the API response

        Raises:
            httpx.HTTPError: On network errors, HTTP errors, or timeout
        """
        logger.debug(f"GET {endpoint} with timeout={timeout}s")
        return self._client.get(endpoint, timeout=timeout)

    def is_healthy(self) -> bool:
        """Check if Ollama service is responding (with 5-second cache).

        Makes GET request to /api/version with short timeout.
        Does NOT use circuit breaker (diagnostics should work even if circuit is open).
        Results are cached for 5 seconds to avoid excessive health checks.

        Returns:
            True if Ollama responds, False otherwise
        """
        # Check if cache is still valid
        if self._health_cache is not None and self._health_cache_time is not None:
            if datetime.now() - self._health_cache_time < self._health_cache_ttl:
                logger.debug(f"Health check (cached): {self._health_cache}")
                return self._health_cache

        # Cache expired or doesn't exist - perform actual check
        try:
            # Use shorter timeout for health checks (pass as float, not httpx.Timeout)
            response = self._client.get("/api/version", timeout=self.health_timeout)
            response.raise_for_status()
            self._health_cache = True
            self._health_cache_time = datetime.now()
            logger.debug("Ollama health check: OK")
            return True
        except Exception as e:
            self._health_cache = False
            self._health_cache_time = datetime.now()
            logger.warning(f"Ollama health check failed: {e}")
            return False

    def get_stats(self) -> dict:
        """Get current client statistics.

        Returns:
            Dict with circuit breaker state, timeouts, connection pool settings
        """
        return {
            "base_url": self.base_url,
            "default_timeout": self.default_timeout,
            "llm_timeout": self.llm_timeout,
            "health_timeout": self.health_timeout,
            "max_connections": self.max_connections,
            "max_keepalive_connections": self.max_keepalive_connections,
            "max_retries": self.max_retries,
            "retry_base_delay": self.retry_base_delay,
            "retry_max_delay": self.retry_max_delay,
            "circuit_breaker_state": self.circuit_breaker.get_state().value,
            "circuit_breaker_threshold": self.circuit_breaker.threshold,
            "is_healthy": self.is_healthy()
        }
