"""Generic HTTP client factory with connection pooling and resilience features.

Provides thread-safe HTTP clients with circuit breaker protection, retry logic,
and support for both synchronous and asynchronous operations (for streaming).
"""

import logging
import random
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from stache_ai.providers.resilience.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class HttpClientConfig:
    """Configuration for HTTP client resilience features."""

    # Connection settings
    base_url: str
    headers: dict[str, str]

    # Timeout settings (seconds)
    default_timeout: float = 60.0
    connect_timeout: float = 10.0
    write_timeout: float = 10.0
    pool_timeout: float = 5.0

    # Connection pool limits
    max_connections: int = 50
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 30.0

    # Retry configuration
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 10.0

    # Circuit breaker configuration
    circuit_breaker_threshold: int = 15
    circuit_breaker_timeout: float = 60.0
    circuit_breaker_half_open_max_calls: int = 3

    def __post_init__(self):
        """Validate configuration."""
        self.base_url = self.base_url.rstrip("/")

        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.retry_base_delay <= 0:
            raise ValueError(f"retry_base_delay must be > 0, got {self.retry_base_delay}")
        if self.retry_max_delay < self.retry_base_delay:
            raise ValueError(
                f"retry_max_delay ({self.retry_max_delay}) must be >= "
                f"retry_base_delay ({self.retry_base_delay})"
            )
        if self.max_connections < self.max_keepalive_connections:
            raise ValueError(
                f"max_connections ({self.max_connections}) must be >= "
                f"max_keepalive_connections ({self.max_keepalive_connections})"
            )
        if self.circuit_breaker_threshold <= 0:
            raise ValueError(
                f"circuit_breaker_threshold must be > 0, got {self.circuit_breaker_threshold}"
            )


class HttpClient:
    """Thread-safe HTTP client with circuit breaker and retry logic.

    Supports both synchronous and asynchronous operations for streaming.
    Each client instance manages its own circuit breaker state.
    """

    def __init__(self, config: HttpClientConfig):
        """Initialize HTTP client with sync and async clients.

        Args:
            config: HttpClientConfig with all resilience settings
        """
        self.config = config

        # Shared timeout configuration
        timeout_config = httpx.Timeout(
            connect=config.connect_timeout,
            read=config.default_timeout,
            write=config.write_timeout,
            pool=config.pool_timeout
        )

        # Shared connection limits
        limits_config = httpx.Limits(
            max_connections=config.max_connections,
            max_keepalive_connections=config.max_keepalive_connections,
            keepalive_expiry=config.keepalive_expiry
        )

        # Synchronous client (for regular operations)
        self._sync_client = httpx.Client(
            base_url=config.base_url,
            timeout=timeout_config,
            limits=limits_config,
            headers=config.headers,
            follow_redirects=True
        )

        # Asynchronous client (for streaming operations)
        self._async_client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=timeout_config,
            limits=limits_config,
            headers=config.headers,
            follow_redirects=True
        )

        # Circuit breaker (shared across sync and async)
        self.circuit_breaker = CircuitBreaker(
            threshold=config.circuit_breaker_threshold,
            timeout=config.circuit_breaker_timeout,
            half_open_max_calls=config.circuit_breaker_half_open_max_calls
        )

        logger.debug(
            f"Initialized HttpClient: base_url={config.base_url}, "
            f"timeout={config.default_timeout}s, "
            f"max_connections={config.max_connections}"
        )

    def with_retry(self, operation: Callable[[], Any], operation_name: str) -> Any:
        """Execute synchronous operation with exponential backoff retry logic.

        Integrates with circuit breaker - checks can_attempt() before each try,
        records success/failure after operation completes. Includes structured
        logging with request IDs for traceability.

        Args:
            operation: Callable that performs the HTTP request
            operation_name: Human-readable name for logging

        Returns:
            Result of operation (httpx.Response)

        Raises:
            RuntimeError: If circuit breaker is OPEN
            Exception: If all retries exhausted
        """
        request_id = str(uuid.uuid4())[:8]

        for attempt in range(self.config.max_retries + 1):
            # Check circuit breaker before attempting
            if not self.circuit_breaker.can_attempt():
                logger.warning(
                    f"[{request_id}] {operation_name} rejected - circuit breaker OPEN"
                )
                raise RuntimeError("Circuit breaker OPEN - rejecting request")

            try:
                # Execute the operation
                result = operation()

                # Log successful retry recovery
                if attempt > 0:
                    logger.info(
                        f"[{request_id}] {operation_name} succeeded on retry "
                        f"attempt {attempt + 1}/{self.config.max_retries + 1}"
                    )
                else:
                    logger.debug(
                        f"[{request_id}] {operation_name} succeeded on first attempt"
                    )

                self.circuit_breaker.record_success()
                return result
            except Exception as e:
                # If this was the last attempt, record failure and raise
                if attempt == self.config.max_retries:
                    self.circuit_breaker.record_failure()
                    logger.error(
                        f"[{request_id}] {operation_name} failed after "
                        f"{self.config.max_retries} retries: {e}"
                    )
                    raise

                # Calculate delay with exponential backoff and jitter
                delay = min(
                    self.config.retry_base_delay * (2 ** attempt),
                    self.config.retry_max_delay
                )
                jitter = random.uniform(-0.5, 0.5) * delay  # ±50% jitter
                final_delay = max(0, delay + jitter)

                logger.info(
                    f"[{request_id}] {operation_name} attempt "
                    f"{attempt + 1}/{self.config.max_retries + 1} failed: {e}. "
                    f"Retrying in {final_delay:.2f}s..."
                )
                time.sleep(final_delay)

    async def awith_retry(
        self,
        operation: Callable[[], Any],
        operation_name: str
    ) -> Any:
        """Execute asynchronous operation with exponential backoff retry logic.

        Async version of with_retry() for streaming operations.

        Args:
            operation: Async callable that performs the HTTP request
            operation_name: Human-readable name for logging

        Returns:
            Result of operation (httpx.Response)

        Raises:
            RuntimeError: If circuit breaker is OPEN
            Exception: If all retries exhausted
        """
        import asyncio

        request_id = str(uuid.uuid4())[:8]

        for attempt in range(self.config.max_retries + 1):
            if not self.circuit_breaker.can_attempt():
                logger.warning(
                    f"[{request_id}] {operation_name} rejected - circuit breaker OPEN"
                )
                raise RuntimeError("Circuit breaker OPEN - rejecting request")

            try:
                result = await operation()

                if attempt > 0:
                    logger.info(
                        f"[{request_id}] {operation_name} succeeded on retry "
                        f"attempt {attempt + 1}/{self.config.max_retries + 1}"
                    )
                else:
                    logger.debug(
                        f"[{request_id}] {operation_name} succeeded on first attempt"
                    )

                self.circuit_breaker.record_success()
                return result
            except Exception as e:
                if attempt == self.config.max_retries:
                    self.circuit_breaker.record_failure()
                    logger.error(
                        f"[{request_id}] {operation_name} failed after "
                        f"{self.config.max_retries} retries: {e}"
                    )
                    raise

                delay = min(
                    self.config.retry_base_delay * (2 ** attempt),
                    self.config.retry_max_delay
                )
                jitter = random.uniform(-0.5, 0.5) * delay
                final_delay = max(0, delay + jitter)

                logger.info(
                    f"[{request_id}] {operation_name} attempt "
                    f"{attempt + 1}/{self.config.max_retries + 1} failed: {e}. "
                    f"Retrying in {final_delay:.2f}s..."
                )
                await asyncio.sleep(final_delay)

    # Synchronous HTTP methods

    def post(
        self,
        endpoint: str,
        json: dict,
        timeout: float | None = None
    ) -> httpx.Response:
        """Make synchronous POST request with automatic retry and circuit breaker protection.

        Args:
            endpoint: API endpoint (e.g., "/api/embeddings")
            json: JSON payload to send in request body
            timeout: Optional timeout override in seconds

        Returns:
            httpx.Response object

        Raises:
            RuntimeError: If circuit breaker is OPEN
            httpx.HTTPError: On network errors, HTTP errors, or timeout after retries
        """
        def operation():
            actual_timeout = self._build_timeout(timeout)
            return self._sync_client.post(endpoint, json=json, timeout=actual_timeout)

        return self.with_retry(operation, f"POST {endpoint}")

    def get(
        self,
        endpoint: str,
        timeout: float | None = None
    ) -> httpx.Response:
        """Make synchronous GET request with automatic retry and circuit breaker protection.

        Args:
            endpoint: API endpoint (e.g., "/api/version")
            timeout: Optional timeout override in seconds

        Returns:
            httpx.Response object

        Raises:
            RuntimeError: If circuit breaker is OPEN
            httpx.HTTPError: On network errors, HTTP errors, or timeout after retries
        """
        def operation():
            actual_timeout = self._build_timeout(timeout)
            return self._sync_client.get(endpoint, timeout=actual_timeout)

        return self.with_retry(operation, f"GET {endpoint}")

    # Asynchronous HTTP methods (for streaming)

    async def apost(
        self,
        endpoint: str,
        json: dict,
        timeout: float | None = None
    ) -> httpx.Response:
        """Make asynchronous POST request with automatic retry and circuit breaker protection.

        Args:
            endpoint: API endpoint
            json: JSON payload
            timeout: Optional timeout override in seconds

        Returns:
            httpx.Response object

        Raises:
            RuntimeError: If circuit breaker is OPEN
            httpx.HTTPError: On network errors, HTTP errors, or timeout after retries
        """
        async def operation():
            actual_timeout = self._build_timeout(timeout)
            return await self._async_client.post(endpoint, json=json, timeout=actual_timeout)

        return await self.awith_retry(operation, f"POST {endpoint}")

    async def aget(
        self,
        endpoint: str,
        timeout: float | None = None
    ) -> httpx.Response:
        """Make asynchronous GET request with automatic retry and circuit breaker protection.

        Args:
            endpoint: API endpoint
            timeout: Optional timeout override in seconds

        Returns:
            httpx.Response object

        Raises:
            RuntimeError: If circuit breaker is OPEN
            httpx.HTTPError: On network errors, HTTP errors, or timeout after retries
        """
        async def operation():
            actual_timeout = self._build_timeout(timeout)
            return await self._async_client.get(endpoint, timeout=actual_timeout)

        return await self.awith_retry(operation, f"GET {endpoint}")

    async def stream_post(
        self,
        endpoint: str,
        json: dict,
        timeout: float | None = None
    ):
        """Make streaming POST request (for Ollama streaming responses).

        Args:
            endpoint: API endpoint (e.g., "/api/generate")
            json: JSON payload with stream=true
            timeout: Optional timeout override in seconds

        Yields:
            httpx.Response in streaming context

        Example:
            async with client.stream_post("/api/generate", payload) as response:
                async for line in response.aiter_lines():
                    yield json.loads(line)
        """
        actual_timeout = self._build_timeout(timeout)
        logger.debug(f"Streaming POST {endpoint} (timeout={timeout}s)")
        async with self._async_client.stream("POST", endpoint, json=json, timeout=actual_timeout) as response:
            yield response

    # Helper methods

    def _build_timeout(self, timeout: float | None) -> httpx.Timeout | None:
        """Build httpx.Timeout from optional override."""
        if timeout is None:
            return None

        return httpx.Timeout(
            connect=self.config.connect_timeout,
            read=timeout,
            write=self.config.write_timeout,
            pool=self.config.pool_timeout
        )

    def close(self):
        """Close synchronous HTTP client."""
        if hasattr(self, "_sync_client") and self._sync_client:
            self._sync_client.close()
            logger.debug("Closed synchronous HTTP client")

    async def aclose(self):
        """Close asynchronous HTTP client."""
        if hasattr(self, "_async_client") and self._async_client:
            await self._async_client.aclose()
            logger.debug("Closed asynchronous HTTP client")

    def get_stats(self) -> dict:
        """Get current client statistics.

        Returns:
            Dict with circuit breaker state, timeouts, connection pool settings
        """
        return {
            "base_url": self.config.base_url,
            "default_timeout": self.config.default_timeout,
            "max_connections": self.config.max_connections,
            "max_keepalive_connections": self.config.max_keepalive_connections,
            "max_retries": self.config.max_retries,
            "retry_base_delay": self.config.retry_base_delay,
            "retry_max_delay": self.config.retry_max_delay,
            "circuit_breaker_state": self.circuit_breaker.get_state().value,
            "circuit_breaker_threshold": self.circuit_breaker.threshold,
        }


class HttpClientFactory:
    """Factory for creating and managing HTTP client instances.

    Uses registry pattern instead of singleton - each provider gets its own
    client instance with separate circuit breaker state. Clients are cached
    by provider name for reuse across requests.

    Thread-safe: Uses double-checked locking for client creation.
    """

    _clients: dict[str, HttpClient] = {}
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_client(cls, provider_name: str, config: HttpClientConfig) -> HttpClient:
        """Get or create HTTP client for a provider (thread-safe).

        Uses double-checked locking pattern:
        1. Check without lock (fast path for subsequent calls)
        2. Acquire lock if needed
        3. Check again to prevent race conditions

        Args:
            provider_name: Unique provider identifier (e.g., "ollama", "mixedbread")
            config: HttpClientConfig with all resilience settings

        Returns:
            HttpClient instance cached for this provider

        Example:
            config = HttpClientConfig(
                base_url="https://api.mixedbread.com",
                headers={"Authorization": f"Bearer {api_key}"},
                max_retries=3
            )
            client = HttpClientFactory.get_client("mixedbread", config)
        """
        # Fast path: client already exists
        if provider_name in cls._clients:
            return cls._clients[provider_name]

        # Slow path: need to create client
        with cls._lock:
            # Double-check after acquiring lock
            if provider_name in cls._clients:
                return cls._clients[provider_name]

            # Create new client
            logger.info(f"Creating HttpClient for provider: {provider_name}")
            client = HttpClient(config)
            cls._clients[provider_name] = client
            logger.info(
                f"HttpClient initialized for {provider_name}: "
                f"base_url={config.base_url}, "
                f"timeout={config.default_timeout}s, "
                f"max_retries={config.max_retries}"
            )
            return client

    @classmethod
    def reset(cls):
        """Reset all clients (for testing only).

        Closes all existing clients and clears the registry.
        Not thread-safe - should only be called from test fixtures.
        """
        with cls._lock:
            for provider_name, client in cls._clients.items():
                try:
                    client.close()
                except Exception as e:
                    logger.warning(
                        f"Error closing client for {provider_name}: {e}"
                    )
            cls._clients.clear()
            logger.debug("HttpClientFactory reset - all clients closed")

    @classmethod
    async def areset(cls):
        """Async version of reset() for closing async clients.

        Should be called from async test fixtures or application shutdown.
        """
        with cls._lock:
            for provider_name, client in cls._clients.items():
                try:
                    await client.aclose()
                except Exception as e:
                    logger.warning(
                        f"Error closing async client for {provider_name}: {e}"
                    )
            cls._clients.clear()
            logger.debug("HttpClientFactory reset (async) - all clients closed")
