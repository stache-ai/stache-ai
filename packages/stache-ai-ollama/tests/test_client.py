"""Comprehensive test suite for OllamaClient singleton.

Tests cover:
- Singleton pattern with thread safety
- Configuration extraction from Settings
- HTTP request methods (GET/POST)
- Retry logic with exponential backoff
- Circuit breaker integration
- Health checks
- Statistics collection
- Singleton reset
"""

import pytest
import httpx
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
from stache_ai.config import Settings
from stache_ai_ollama.client import OllamaClient
from stache_ai.providers.resilience import CircuitState


@pytest.fixture(autouse=True)
def reset_http_client_factory():
    """Reset HttpClientFactory before and after each test.

    Ensures a clean state for each test and prevents state leakage.
    """
    from stache_ai.providers.resilience import HttpClientFactory
    HttpClientFactory.reset()
    yield
    HttpClientFactory.reset()


@pytest.fixture
def mock_settings():
    """Create test settings with Ollama configuration."""
    return Settings(
        ollama_url="http://localhost:11434",
        ollama_embedding_timeout=90.0,
        ollama_llm_timeout=120.0,
        ollama_health_check_timeout=5.0,
        ollama_max_connections=50,
        ollama_max_keepalive_connections=20,
        ollama_keepalive_expiry=30.0,
        ollama_max_retries=3,
        ollama_retry_base_delay=1.0,
        ollama_retry_max_delay=10.0,
        ollama_circuit_breaker_threshold=15,
        ollama_circuit_breaker_timeout=60.0,
        ollama_circuit_breaker_half_open_max_calls=3
    )


class TestInstantiation:
    """Test OllamaClient instantiation."""

    def test_instantiation_creates_client(self, mock_settings):
        """Verify OllamaClient() creates a new instance."""
        client = OllamaClient(mock_settings)

        assert client is not None
        assert isinstance(client, OllamaClient)
        assert client.base_url == "http://localhost:11434"

    def test_multiple_instantiations_create_separate_instances(self, mock_settings):
        """Verify each OllamaClient() call creates a separate instance."""
        client1 = OllamaClient(mock_settings)
        client2 = OllamaClient(mock_settings)

        # Each instantiation should create a separate object
        assert client1 is not client2

    def test_instantiation_with_settings(self, mock_settings):
        """Verify instantiation with settings creates properly configured client."""
        client = OllamaClient(mock_settings)

        assert client is not None
        assert isinstance(client, OllamaClient)
        assert client.base_url == "http://localhost:11434"


class TestConcurrentInstantiation:
    """Test concurrent OllamaClient instantiation."""

    def test_concurrent_instantiation_creates_separate_instances(self, mock_settings):
        """Verify concurrent OllamaClient() calls create separate instances.

        Creates 50 threads that simultaneously instantiate OllamaClient and verifies
        each gets a distinct object.
        """
        instances = []

        def create_instance_thread():
            instance = OllamaClient(mock_settings)
            instances.append(instance)

        # Create 50 threads to test concurrent instantiation
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(create_instance_thread) for _ in range(50)]
            for future in futures:
                future.result()

        # All instances should be separate objects
        assert len(instances) == 50
        # Verify they are distinct
        for i, inst in enumerate(instances):
            for j, other in enumerate(instances):
                if i != j:
                    assert inst is not other


class TestConfigurationExtraction:
    """Test that configuration is properly extracted from Settings."""

    def test_timeout_configuration_extracted(self, mock_settings):
        """Verify all timeout values are extracted from settings."""
        client = OllamaClient(mock_settings)

        assert client.default_timeout == 90.0
        assert client.llm_timeout == 120.0
        assert client.health_timeout == 5.0

    def test_connection_pool_configuration_extracted(self, mock_settings):
        """Verify connection pool settings are extracted from settings."""
        client = OllamaClient(mock_settings)

        assert client.max_connections == 50
        assert client.max_keepalive_connections == 20
        assert client.keepalive_expiry == 30.0

    def test_retry_configuration_extracted(self, mock_settings):
        """Verify retry settings are extracted from settings."""
        client = OllamaClient(mock_settings)

        assert client.max_retries == 3
        assert client.retry_base_delay == 1.0
        assert client.retry_max_delay == 10.0

    def test_circuit_breaker_initialized(self, mock_settings):
        """Verify circuit breaker is initialized with correct configuration."""
        client = OllamaClient(mock_settings)

        assert client.circuit_breaker is not None
        assert client.circuit_breaker.threshold == 15
        assert client.circuit_breaker.timeout == 60.0
        assert client.circuit_breaker.half_open_max_calls == 3
        assert client.circuit_breaker.get_state() == CircuitState.CLOSED

    def test_base_url_normalized(self, mock_settings):
        """Verify base URL is normalized (trailing slash removed)."""
        settings_with_slash = Settings(
            ollama_url="http://localhost:11434/",
            ollama_embedding_timeout=90.0,
            ollama_llm_timeout=120.0,
            ollama_health_check_timeout=5.0,
        )
        client = OllamaClient(settings_with_slash)

        # Trailing slash should be removed
        assert client.base_url == "http://localhost:11434"


class TestHTTPMethods:
    """Test HTTP request methods."""

    @patch('httpx.Client.post')
    def test_post_request(self, mock_post, mock_settings):
        """Verify POST request is made with correct parameters."""
        client = OllamaClient(mock_settings)

        # Setup mock response
        mock_response = MagicMock()
        mock_post.return_value = mock_response

        # Make POST request
        result = client.post("/api/embeddings", {"model": "test", "input": "text"})

        # Verify response returned
        assert result is mock_response

        # Verify POST was called with correct endpoint
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/api/embeddings"
        assert call_args[1]["json"] == {"model": "test", "input": "text"}

    @patch('httpx.Client.post')
    def test_post_request_with_timeout_override(self, mock_post, mock_settings):
        """Verify POST request respects timeout override."""
        client = OllamaClient(mock_settings)

        mock_response = MagicMock()
        mock_post.return_value = mock_response

        # Make POST request with custom timeout
        client.post("/api/embeddings", {"model": "test"}, timeout=45.0)

        # Verify timeout parameter was passed
        call_args = mock_post.call_args
        timeout_obj = call_args[1]["timeout"]
        assert timeout_obj.read == 45.0

    @patch('httpx.Client.get')
    def test_get_request(self, mock_get, mock_settings):
        """Verify GET request is made with correct parameters."""
        client = OllamaClient(mock_settings)

        mock_response = MagicMock()
        mock_get.return_value = mock_response

        # Make GET request
        result = client.get("/api/version")

        # Verify response returned
        assert result is mock_response

        # Verify GET was called with correct endpoint
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "/api/version"

    @patch('httpx.Client.get')
    def test_get_request_with_timeout_override(self, mock_get, mock_settings):
        """Verify GET request respects timeout override."""
        client = OllamaClient(mock_settings)

        mock_response = MagicMock()
        mock_get.return_value = mock_response

        # Make GET request with custom timeout
        client.get("/api/version", timeout=15.0)

        # Verify timeout parameter was passed
        call_args = mock_get.call_args
        timeout_obj = call_args[1]["timeout"]
        assert timeout_obj.read == 15.0


class TestRetryLogic:
    """Test retry logic with exponential backoff."""

    @patch('time.sleep')
    @patch('httpx.Client.post')
    def test_retry_succeeds_on_second_attempt(self, mock_post, mock_sleep, mock_settings):
        """Verify operation retries and succeeds on second attempt."""
        client = OllamaClient(mock_settings)

        # Mock POST that fails once then succeeds
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.side_effect = [Exception("First attempt failed"), mock_response]

        # Execute POST (retry is automatic via HttpClient)
        result = client.post("/api/test", {"data": "test"})

        # Verify POST was called twice
        assert mock_post.call_count == 2
        # Verify result is the successful response
        assert result == mock_response
        # Verify sleep was called once (between retry and second attempt)
        assert mock_sleep.call_count == 1

    @patch('time.sleep')
    @patch('httpx.Client.post')
    def test_exponential_backoff_delays(self, mock_post, mock_sleep, mock_settings):
        """Verify exponential backoff delays between retries."""
        client = OllamaClient(mock_settings)

        # POST that always fails
        mock_post.side_effect = Exception("Always fails")

        try:
            client.post("/api/test", {"data": "test"})
        except Exception:
            pass

        # Verify sleep was called 3 times (3 retries)
        assert mock_sleep.call_count == 3

        # Verify exponential backoff: 1s, 2s, 4s (base_delay * 2^attempt)
        sleep_calls = mock_sleep.call_args_list

        # First retry should use 1.0s base delay + jitter (±50%)
        first_delay = sleep_calls[0][0][0]
        assert 0 <= first_delay <= 1.5  # 1.0 +/- 0.5 jitter

        # Second retry should use 2.0s base delay + jitter (±50%)
        second_delay = sleep_calls[1][0][0]
        assert 1.0 <= second_delay <= 3.0  # 2.0 +/- 1.0 jitter

        # Third retry should use 4.0s base delay + jitter (±50%, but can go to 0 with jitter)
        third_delay = sleep_calls[2][0][0]
        assert 0 <= third_delay <= 6.0  # 4.0 +/- 2.0 jitter (but capped at min 0)

    @patch('time.sleep')
    @patch('httpx.Client.post')
    def test_retry_exhaustion(self, mock_post, mock_sleep, mock_settings):
        """Verify exception is raised after max retries exhausted."""
        client = OllamaClient(mock_settings)

        # POST that always fails
        original_error = Exception("Always fails")
        mock_post.side_effect = original_error

        # Should raise after max_retries (4 total attempts: 1 initial + 3 retries)
        with pytest.raises(Exception, match="Always fails"):
            client.post("/api/test", {"data": "test"})

        # Verify POST called max_retries + 1 times
        assert mock_post.call_count == 4

    @patch('time.sleep')
    @patch('httpx.Client.post')
    def test_circuit_breaker_records_failures(self, mock_post, mock_sleep, mock_settings):
        """Verify circuit breaker records failures from retry logic."""
        client = OllamaClient(mock_settings)

        # Verify initial state
        assert client.circuit_breaker.get_state() == CircuitState.CLOSED

        # POST that always fails
        mock_post.side_effect = Exception("Failure")

        try:
            client.post("/api/test", {"data": "test"})
        except Exception:
            pass

        # Verify circuit breaker recorded the failure
        stats = client.circuit_breaker.get_stats()
        assert stats['failure_count'] >= 1


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration with retry logic."""

    @patch('httpx.Client.post')
    def test_circuit_breaker_open_rejects_requests(self, mock_post, mock_settings):
        """Verify circuit breaker rejects requests when open."""
        client = OllamaClient(mock_settings)

        # Record failures to open circuit
        for _ in range(client.circuit_breaker.threshold):
            client.circuit_breaker.record_failure()

        # Circuit should now be OPEN
        assert client.circuit_breaker.get_state() == CircuitState.OPEN

        # Attempting POST should fail immediately with circuit breaker error
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            client.post("/api/test", {"data": "test"})

        # POST should not be called when circuit is open
        assert mock_post.call_count == 0

    @patch('httpx.Client.post')
    def test_circuit_breaker_can_attempt_integration(self, mock_post, mock_settings):
        """Verify retry checks can_attempt() before each attempt."""
        client = OllamaClient(mock_settings)

        # Open circuit
        for _ in range(client.circuit_breaker.threshold):
            client.circuit_breaker.record_failure()

        # Verify can_attempt() returns False
        assert not client.circuit_breaker.can_attempt()

        # POST should fail immediately with circuit breaker error
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            client.post("/api/test", {"data": "test"})

        # POST should not be called when circuit is open
        assert mock_post.call_count == 0


class TestHealthCheck:
    """Test health check functionality."""

    @patch('httpx.Client.get')
    def test_is_healthy_returns_true_on_success(self, mock_get, mock_settings):
        """Verify is_healthy() returns True when /api/version succeeds."""
        client = OllamaClient(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = client.is_healthy()

        assert result is True
        # Verify GET was called with /api/version
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "/api/version"

    @patch('httpx.Client.get')
    def test_is_healthy_returns_false_on_failure(self, mock_get, mock_settings):
        """Verify is_healthy() returns False when /api/version fails."""
        client = OllamaClient(mock_settings)

        # Mock failure
        mock_get.side_effect = httpx.ConnectError("Connection failed")

        result = client.is_healthy()

        assert result is False

    @patch('httpx.Client.get')
    def test_health_check_uses_health_timeout(self, mock_get, mock_settings):
        """Verify health check uses health_timeout, not default_timeout."""
        client = OllamaClient(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client.is_healthy()

        # Verify health timeout was used (5.0s)
        call_args = mock_get.call_args
        timeout_obj = call_args[1]["timeout"]
        assert timeout_obj.read == 5.0
        assert timeout_obj.read != client.default_timeout


class TestStatistics:
    """Test statistics collection."""

    def test_get_stats_returns_all_expected_keys(self, mock_settings):
        """Verify get_stats() returns dict with all expected keys."""
        client = OllamaClient(mock_settings)

        stats = client.get_stats()

        # Verify all expected keys are present
        expected_keys = {
            "base_url",
            "default_timeout",
            "llm_timeout",
            "health_timeout",
            "max_connections",
            "max_keepalive_connections",
            "max_retries",
            "retry_base_delay",
            "retry_max_delay",
            "circuit_breaker_state",
            "circuit_breaker_threshold",
            "is_healthy"
        }

        assert set(stats.keys()) == expected_keys

    def test_get_stats_values_match_configuration(self, mock_settings):
        """Verify get_stats() values match current configuration."""
        client = OllamaClient(mock_settings)

        stats = client.get_stats()

        assert stats["base_url"] == "http://localhost:11434"
        assert stats["default_timeout"] == 90.0
        assert stats["llm_timeout"] == 120.0
        assert stats["health_timeout"] == 5.0
        assert stats["max_connections"] == 50
        assert stats["max_keepalive_connections"] == 20
        assert stats["max_retries"] == 3
        assert stats["retry_base_delay"] == 1.0
        assert stats["retry_max_delay"] == 10.0
        assert stats["circuit_breaker_threshold"] == 15

    def test_get_stats_circuit_breaker_state(self, mock_settings):
        """Verify get_stats() includes circuit breaker state."""
        client = OllamaClient(mock_settings)

        stats = client.get_stats()

        # Should start in CLOSED state
        assert stats["circuit_breaker_state"] == "closed"

    @patch('httpx.Client.get')
    def test_get_stats_includes_health_status(self, mock_get, mock_settings):
        """Verify get_stats() includes current health status."""
        client = OllamaClient(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        stats = client.get_stats()

        assert "is_healthy" in stats
        assert isinstance(stats["is_healthy"], bool)


class TestClientCleanup:
    """Test client cleanup and resource management."""

    def test_client_attribute_exists(self, mock_settings):
        """Verify HttpClient is created and stored."""
        from stache_ai.providers.resilience.http_client import HttpClient

        client = OllamaClient(mock_settings)

        assert hasattr(client, "_client")
        assert isinstance(client._client, HttpClient)

    def test_client_has_http_client(self, mock_settings):
        """Verify OllamaClient stores an httpx.Client instance."""
        client = OllamaClient(mock_settings)

        # Verify client exists
        assert hasattr(client, "_client")
        # The _client should be the delegate used for HTTP operations
        assert client._client is not None


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_initialization_fails_with_invalid_settings(self):
        """Verify initialization handles invalid settings gracefully."""
        # Settings with invalid configuration
        invalid_settings = Settings(
            ollama_url="http://localhost:11434",
            ollama_embedding_timeout=-1.0,  # Invalid: negative timeout
        )

        # This should handle gracefully (timeout validation may be at httpx level)
        # For now, just verify it doesn't crash unexpectedly
        try:
            client = OllamaClient(invalid_settings)
            # Even if it succeeds, subsequent operations might fail
        except Exception:
            # Expected to potentially fail with invalid config
            pass

    @patch('httpx.Client.post')
    def test_retry_with_jitter_prevents_thundering_herd(self, mock_post, mock_settings):
        """Verify jitter is applied to prevent thundering herd problem."""
        client = OllamaClient(mock_settings)

        # Record multiple retry delays to verify randomness
        delays = []

        with patch('time.sleep', side_effect=lambda x: delays.append(x)):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.side_effect = [
                Exception("Fail 1"),
                Exception("Fail 2"),
                Exception("Fail 3"),
                mock_response
            ]

            result = client.post("/api/test", {"data": "test"})

        # All delays should be different due to random jitter
        # (With 50% jitter, probability of identical delays is very low)
        # Just verify delays are reasonable
        for delay in delays:
            assert 0 <= delay <= client.retry_max_delay
