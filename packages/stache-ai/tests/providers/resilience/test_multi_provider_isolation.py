"""Multi-provider isolation tests for HttpClientFactory.

Verifies that different providers are properly isolated:
- Each provider gets its own HttpClient instance with separate circuit breaker state
- Factory caches clients by provider name (same provider = same client)
- Circuit breaker failures in one provider don't affect others
- Configuration settings are independent per provider
- Concurrent access is thread-safe
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch

from stache_ai.providers.resilience import (
    HttpClientFactory,
    HttpClientConfig,
    CircuitState
)


@pytest.fixture(autouse=True)
def reset_factory():
    """Reset factory before and after each test.

    This ensures clean state and prevents test pollution.
    """
    HttpClientFactory.reset()
    yield
    HttpClientFactory.reset()


class TestFactoryIsolation:
    """Test 1-3: Factory isolation - different providers get different clients."""

    def test_different_providers_get_different_clients(self):
        """Different providers get different HttpClient instances.

        Provider A and Provider B should each get their own client instance
        with separate circuit breaker state and connection pools.
        """
        config_a = HttpClientConfig(
            base_url="http://provider-a.local:8080",
            headers={"Authorization": "Bearer token-a"},
            max_retries=2,
            circuit_breaker_threshold=5
        )
        config_b = HttpClientConfig(
            base_url="http://provider-b.local:9090",
            headers={"Authorization": "Bearer token-b"},
            max_retries=3,
            circuit_breaker_threshold=10
        )

        client_a = HttpClientFactory.get_client("provider_a", config_a)
        client_b = HttpClientFactory.get_client("provider_b", config_b)

        # Different providers = different client instances
        assert client_a is not client_b

        # Each has own config
        assert client_a.config.base_url == "http://provider-a.local:8080"
        assert client_b.config.base_url == "http://provider-b.local:9090"

        # Each has own circuit breaker (separate objects)
        assert client_a.circuit_breaker is not client_b.circuit_breaker

    def test_same_provider_returns_cached_client(self):
        """Same provider returns cached client instance (not re-created).

        Multiple calls to get_client() with same provider name should return
        the same client instance.
        """
        config = HttpClientConfig(
            base_url="http://ollama:11434",
            headers={}
        )

        client_1 = HttpClientFactory.get_client("ollama", config)
        client_2 = HttpClientFactory.get_client("ollama", config)

        # Same provider = same client instance (cached)
        assert client_1 is client_2

        # Verify stats are consistent
        stats_1 = client_1.get_stats()
        stats_2 = client_2.get_stats()
        assert stats_1 == stats_2

    def test_factory_caching_prevents_resource_leak(self):
        """Factory caching prevents creating duplicate clients for same provider.

        Getting the same provider 10 times should only create 1 client,
        not 10 separate clients.
        """
        config = HttpClientConfig(
            base_url="http://service:3000",
            headers={}
        )

        # Get client multiple times
        clients = [
            HttpClientFactory.get_client("service", config)
            for _ in range(10)
        ]

        # All should be the same instance
        for client in clients[1:]:
            assert client is clients[0]


class TestCircuitBreakerIsolation:
    """Test 4-6: Circuit breaker isolation - failures don't cross providers."""

    def test_provider_a_circuit_open_doesnt_affect_provider_b(self):
        """Provider A circuit breaker open doesn't affect Provider B.

        When Provider A fails enough times to open its circuit breaker,
        Provider B should still be able to make requests normally.
        """
        config_a = HttpClientConfig(
            base_url="http://provider-a:8080",
            headers={},
            circuit_breaker_threshold=2
        )
        config_b = HttpClientConfig(
            base_url="http://provider-b:9090",
            headers={},
            circuit_breaker_threshold=10
        )

        client_a = HttpClientFactory.get_client("provider_a", config_a)
        client_b = HttpClientFactory.get_client("provider_b", config_b)

        # Both should start in CLOSED state
        assert client_a.circuit_breaker.get_state() == CircuitState.CLOSED
        assert client_b.circuit_breaker.get_state() == CircuitState.CLOSED

        # Open Provider A's circuit (threshold=2, so 2 failures)
        client_a.circuit_breaker.record_failure()
        client_a.circuit_breaker.record_failure()

        # Provider A is now OPEN
        assert client_a.circuit_breaker.get_state() == CircuitState.OPEN
        assert client_a.circuit_breaker.can_attempt() is False

        # Provider B should still be CLOSED and operational
        assert client_b.circuit_breaker.get_state() == CircuitState.CLOSED
        assert client_b.circuit_breaker.can_attempt() is True

    def test_failure_count_isolation(self):
        """Each provider maintains independent failure counts.

        Recording failures for Provider A should not affect Provider B's
        failure count.
        """
        config_a = HttpClientConfig(
            base_url="http://provider-a:8080",
            headers={},
            circuit_breaker_threshold=10
        )
        config_b = HttpClientConfig(
            base_url="http://provider-b:9090",
            headers={},
            circuit_breaker_threshold=10
        )

        client_a = HttpClientFactory.get_client("provider_a", config_a)
        client_b = HttpClientFactory.get_client("provider_b", config_b)

        # Record 5 failures for Provider A
        for _ in range(5):
            client_a.circuit_breaker.record_failure()

        # Provider A should have 5 failures
        stats_a = client_a.circuit_breaker.get_stats()
        assert stats_a["failure_count"] == 5
        assert stats_a["state"] == "closed"  # Not yet open (threshold=10)

        # Provider B should still have 0 failures
        stats_b = client_b.circuit_breaker.get_stats()
        assert stats_b["failure_count"] == 0
        assert stats_b["state"] == "closed"

    def test_circuit_state_independence(self):
        """Each provider has independent circuit breaker state.

        Provider A transitioning between states should not change Provider B's state.
        """
        config_a = HttpClientConfig(
            base_url="http://provider-a:8080",
            headers={},
            circuit_breaker_threshold=1,
            circuit_breaker_timeout=0.5
        )
        config_b = HttpClientConfig(
            base_url="http://provider-b:9090",
            headers={},
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=0.5
        )

        client_a = HttpClientFactory.get_client("provider_a", config_a)
        client_b = HttpClientFactory.get_client("provider_b", config_b)

        # Move Provider A to OPEN
        client_a.circuit_breaker.record_failure()
        assert client_a.circuit_breaker.get_state() == CircuitState.OPEN

        # Provider B should remain CLOSED
        assert client_b.circuit_breaker.get_state() == CircuitState.CLOSED

        # Move Provider A to HALF_OPEN by waiting for timeout
        time.sleep(0.6)

        # Trigger state check on A
        client_a.circuit_breaker.can_attempt()
        assert client_a.circuit_breaker.get_state() == CircuitState.HALF_OPEN

        # Provider B should still be CLOSED
        assert client_b.circuit_breaker.get_state() == CircuitState.CLOSED


class TestConfigurationIsolation:
    """Test 7-8: Configuration isolation - settings are independent per provider."""

    def test_different_timeouts_per_provider(self):
        """Different providers can have different timeout configurations.

        Provider A with 30s timeout, Provider B with 120s timeout should each
        use their configured timeout values independently.
        """
        config_a = HttpClientConfig(
            base_url="http://provider-a:8080",
            headers={},
            default_timeout=30.0,
            connect_timeout=5.0
        )
        config_b = HttpClientConfig(
            base_url="http://provider-b:9090",
            headers={},
            default_timeout=120.0,
            connect_timeout=15.0
        )

        client_a = HttpClientFactory.get_client("provider_a", config_a)
        client_b = HttpClientFactory.get_client("provider_b", config_b)

        # Provider A has short timeout
        assert client_a.config.default_timeout == 30.0
        assert client_a.config.connect_timeout == 5.0

        # Provider B has long timeout
        assert client_b.config.default_timeout == 120.0
        assert client_b.config.connect_timeout == 15.0

        # Verify in stats
        stats_a = client_a.get_stats()
        stats_b = client_b.get_stats()
        assert stats_a["default_timeout"] == 30.0
        assert stats_b["default_timeout"] == 120.0

    def test_different_retry_settings_per_provider(self):
        """Different providers can have different retry configurations.

        Provider A (unreliable service) with 5 retries, Provider B (reliable service)
        with 1 retry should each use their independent retry settings.
        """
        config_a = HttpClientConfig(
            base_url="http://flaky-service:8080",
            headers={},
            max_retries=5,
            retry_base_delay=2.0,
            retry_max_delay=30.0
        )
        config_b = HttpClientConfig(
            base_url="http://reliable-service:9090",
            headers={},
            max_retries=1,
            retry_base_delay=0.5,
            retry_max_delay=2.0
        )

        client_a = HttpClientFactory.get_client("flaky", config_a)
        client_b = HttpClientFactory.get_client("reliable", config_b)

        # Provider A: aggressive retry strategy
        assert client_a.config.max_retries == 5
        assert client_a.config.retry_base_delay == 2.0
        assert client_a.config.retry_max_delay == 30.0

        # Provider B: conservative retry strategy
        assert client_b.config.max_retries == 1
        assert client_b.config.retry_base_delay == 0.5
        assert client_b.config.retry_max_delay == 2.0

        # Verify in stats
        stats_a = client_a.get_stats()
        stats_b = client_b.get_stats()
        assert stats_a["max_retries"] == 5
        assert stats_b["max_retries"] == 1


class TestConcurrentAccess:
    """Test 9: Concurrent access to factory from multiple providers (bonus test)."""

    def test_concurrent_get_client_calls_are_thread_safe(self):
        """Concurrent calls to get_client() are thread-safe.

        Multiple threads calling get_client() for different providers simultaneously
        should properly create and cache clients without race conditions.
        """
        results = {}
        errors = []

        def create_client(provider_name, provider_id):
            """Create client for a provider."""
            try:
                config = HttpClientConfig(
                    base_url=f"http://{provider_name}:{8000 + provider_id}",
                    headers={"Provider-ID": str(provider_id)}
                )
                client = HttpClientFactory.get_client(provider_name, config)
                results[provider_name] = client
            except Exception as e:
                errors.append((provider_name, e))

        # Create 5 providers concurrently
        threads = [
            threading.Thread(
                target=create_client,
                args=(f"provider_{i}", i)
            )
            for i in range(5)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Should have no errors
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"

        # Should have created 5 different clients
        assert len(results) == 5
        client_ids = [id(client) for client in results.values()]
        assert len(set(client_ids)) == 5  # All different instances

    def test_concurrent_client_use_is_thread_safe(self):
        """Concurrent use of same client from multiple threads is thread-safe.

        Multiple threads calling with_retry() on the same client simultaneously
        should not cause race conditions in circuit breaker state.
        """
        config = HttpClientConfig(
            base_url="http://service:8080",
            headers={},
            max_retries=0,
            circuit_breaker_threshold=100  # High threshold to avoid opening
        )
        client = HttpClientFactory.get_client("service", config)

        success_count = []
        errors = []

        def call_operation():
            """Call a simple operation on the client."""
            try:
                # Mock operation that succeeds
                def op():
                    return "success"

                result = client.with_retry(op, "test_operation")
                success_count.append(result)
            except Exception as e:
                errors.append(e)

        # Run 10 concurrent threads using the same client
        threads = [
            threading.Thread(target=call_operation)
            for _ in range(10)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # All should succeed
        assert len(errors) == 0, f"Errors during concurrent use: {errors}"
        assert len(success_count) == 10

        # Circuit breaker should still be CLOSED
        assert client.circuit_breaker.get_state() == CircuitState.CLOSED


class TestFactoryReset:
    """Test 10: Factory reset functionality (bonus test)."""

    def test_factory_reset_clears_all_clients(self):
        """Factory.reset() clears all cached clients.

        After reset, subsequent get_client() calls should create fresh clients
        with fresh circuit breaker state.
        """
        config_a = HttpClientConfig(
            base_url="http://provider-a:8080",
            headers={},
            circuit_breaker_threshold=2
        )
        config_b = HttpClientConfig(
            base_url="http://provider-b:9090",
            headers={},
            circuit_breaker_threshold=2
        )

        # Create clients
        client_a_v1 = HttpClientFactory.get_client("provider_a", config_a)
        client_b_v1 = HttpClientFactory.get_client("provider_b", config_b)

        # Open their circuits
        client_a_v1.circuit_breaker.record_failure()
        client_a_v1.circuit_breaker.record_failure()
        client_b_v1.circuit_breaker.record_failure()
        client_b_v1.circuit_breaker.record_failure()

        assert client_a_v1.circuit_breaker.get_state() == CircuitState.OPEN
        assert client_b_v1.circuit_breaker.get_state() == CircuitState.OPEN

        # Reset factory
        HttpClientFactory.reset()

        # Get clients again
        client_a_v2 = HttpClientFactory.get_client("provider_a", config_a)
        client_b_v2 = HttpClientFactory.get_client("provider_b", config_b)

        # Should be fresh instances
        assert client_a_v2 is not client_a_v1
        assert client_b_v2 is not client_b_v1

        # Should have fresh circuit breaker state (CLOSED)
        assert client_a_v2.circuit_breaker.get_state() == CircuitState.CLOSED
        assert client_b_v2.circuit_breaker.get_state() == CircuitState.CLOSED
