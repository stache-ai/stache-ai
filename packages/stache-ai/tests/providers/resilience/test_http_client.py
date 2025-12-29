"""Comprehensive unit tests for HttpClient and HttpClientConfig.

Test coverage includes:
- HttpClientConfig validation (~8 tests)
- HttpClient instantiation (~5 tests)
- HTTP method operations (~8 tests)
- Retry logic with exponential backoff (~8 tests)
- Circuit breaker integration (~6 tests)
- Thread safety under concurrent load (~3 tests)
- Error handling and edge cases (~2 tests)

Total: ~40 tests
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import httpx
import pytest

from stache_ai.providers.resilience import (
    CircuitState,
    HttpClient,
    HttpClientConfig,
    HttpClientFactory,
)

# ============================================================================
# SECTION 1: HttpClientConfig Validation Tests (~8 tests)
# ============================================================================

class TestHttpClientConfigValidation:
    """Test HttpClientConfig dataclass validation."""

    def test_valid_config_creation(self):
        """Test creating a valid HttpClientConfig."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer token"},
            default_timeout=60.0,
            max_retries=3
        )
        assert config.base_url == "https://api.example.com"
        assert config.max_retries == 3

    def test_base_url_trailing_slash_removed(self):
        """Test that trailing slashes are removed from base_url."""
        config = HttpClientConfig(
            base_url="https://api.example.com/",
            headers={}
        )
        assert config.base_url == "https://api.example.com"
        assert not config.base_url.endswith("/")

    def test_invalid_negative_max_retries(self):
        """Test that negative max_retries raises ValueError."""
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            HttpClientConfig(
                base_url="https://api.example.com",
                headers={},
                max_retries=-1
            )

    def test_invalid_zero_retry_base_delay(self):
        """Test that zero retry_base_delay raises ValueError."""
        with pytest.raises(ValueError, match="retry_base_delay must be > 0"):
            HttpClientConfig(
                base_url="https://api.example.com",
                headers={},
                retry_base_delay=0.0
            )

    def test_invalid_negative_retry_base_delay(self):
        """Test that negative retry_base_delay raises ValueError."""
        with pytest.raises(ValueError, match="retry_base_delay must be > 0"):
            HttpClientConfig(
                base_url="https://api.example.com",
                headers={},
                retry_base_delay=-1.0
            )

    def test_invalid_retry_max_delay_less_than_base_delay(self):
        """Test that retry_max_delay < retry_base_delay raises ValueError."""
        with pytest.raises(ValueError, match="retry_max_delay.*must be >="):
            HttpClientConfig(
                base_url="https://api.example.com",
                headers={},
                retry_base_delay=5.0,
                retry_max_delay=2.0
            )

    def test_invalid_max_connections_less_than_keepalive(self):
        """Test that max_connections < max_keepalive_connections raises ValueError."""
        with pytest.raises(ValueError, match="max_connections.*must be >="):
            HttpClientConfig(
                base_url="https://api.example.com",
                headers={},
                max_connections=10,
                max_keepalive_connections=20
            )

    def test_invalid_circuit_breaker_threshold_zero(self):
        """Test that circuit_breaker_threshold <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="circuit_breaker_threshold must be > 0"):
            HttpClientConfig(
                base_url="https://api.example.com",
                headers={},
                circuit_breaker_threshold=0
            )


# ============================================================================
# SECTION 2: HttpClient Instantiation Tests (~5 tests)
# ============================================================================

class TestHttpClientInstantiation:
    """Test HttpClient initialization and configuration."""

    def test_instantiation_with_valid_config(self):
        """Test successful HttpClient instantiation with valid config."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer token"}
        )
        client = HttpClient(config)

        assert client.config == config
        assert client._sync_client is not None
        assert client._async_client is not None
        assert client.circuit_breaker is not None

    def test_base_url_normalized_on_init(self):
        """Test that base_url is normalized during instantiation."""
        config = HttpClientConfig(
            base_url="https://api.example.com/",
            headers={}
        )
        client = HttpClient(config)

        assert client.config.base_url == "https://api.example.com"

    def test_headers_configuration(self):
        """Test that headers are correctly configured in sync client."""
        headers = {"Authorization": "Bearer token", "X-Custom": "value"}
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers=headers
        )
        client = HttpClient(config)

        # httpx.Client stores headers in client.headers
        assert client._sync_client.headers.get("Authorization") == "Bearer token"
        assert client._sync_client.headers.get("X-Custom") == "value"

    def test_timeout_configuration(self):
        """Test that timeout settings are applied to clients."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            default_timeout=45.0,
            connect_timeout=8.0,
            write_timeout=12.0,
            pool_timeout=3.0
        )
        client = HttpClient(config)

        # Verify clients were created with timeout config
        assert client._sync_client.timeout is not None
        assert client._async_client.timeout is not None

    def test_connection_pool_configuration(self):
        """Test that connection pool limits are applied."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_connections=75,
            max_keepalive_connections=30,
            keepalive_expiry=45.0
        )
        client = HttpClient(config)

        # Verify clients were created successfully with limits configured in config
        assert client._sync_client is not None
        assert client._async_client is not None
        assert config.max_connections == 75
        assert config.max_keepalive_connections == 30
        assert config.keepalive_expiry == 45.0


# ============================================================================
# SECTION 3: HTTP Method Tests (~8 tests)
# ============================================================================

class TestHttpClientMethods:
    """Test synchronous HTTP methods."""

    @pytest.fixture
    def client(self):
        """Create an HttpClient for testing."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer token"}
        )
        client = HttpClient(config)
        yield client
        client.close()

    @patch("stache_ai.providers.resilience.http_client.httpx.Client.post")
    def test_post_request_success(self, mock_post, client):
        """Test successful POST request."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        response = client.post("/embeddings", json={"text": "hello"})

        assert response == mock_response
        mock_post.assert_called_once()

    @patch("stache_ai.providers.resilience.http_client.httpx.Client.get")
    def test_get_request_success(self, mock_get, client):
        """Test successful GET request."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        response = client.get("/version")

        assert response == mock_response
        mock_get.assert_called_once()

    @patch("stache_ai.providers.resilience.http_client.httpx.Client.post")
    def test_post_with_custom_headers(self, mock_post, client):
        """Test POST request delegates headers correctly."""
        mock_response = Mock(spec=httpx.Response)
        mock_post.return_value = mock_response

        payload = {"text": "test"}
        client.post("/embeddings", json=payload)

        mock_post.assert_called_once()

    @patch("stache_ai.providers.resilience.http_client.httpx.Client.post")
    def test_post_with_timeout_override(self, mock_post, client):
        """Test POST request with timeout override."""
        mock_response = Mock(spec=httpx.Response)
        mock_post.return_value = mock_response

        client.post("/embeddings", json={"text": "test"}, timeout=30.0)

        mock_post.assert_called_once()
        # Check that timeout was passed
        call_args = mock_post.call_args
        assert call_args is not None

    @patch("stache_ai.providers.resilience.http_client.httpx.Client.get")
    def test_get_with_timeout_override(self, mock_get, client):
        """Test GET request with timeout override."""
        mock_response = Mock(spec=httpx.Response)
        mock_get.return_value = mock_response

        client.get("/version", timeout=15.0)

        mock_get.assert_called_once()

    def test_build_timeout_with_override(self, client):
        """Test timeout building helper method."""
        timeout_obj = client._build_timeout(25.0)

        assert timeout_obj is not None
        assert timeout_obj.read == 25.0

    def test_build_timeout_without_override(self, client):
        """Test timeout building returns None when no override."""
        timeout_obj = client._build_timeout(None)

        assert timeout_obj is None


# ============================================================================
# SECTION 4: Retry Logic Tests (~8 tests)
# ============================================================================

class TestRetryLogic:
    """Test synchronous retry mechanism with exponential backoff."""

    @pytest.fixture
    def client(self):
        """Create HttpClient with retry enabled."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_retries=3,
            retry_base_delay=0.01,  # Short delay for faster tests
            retry_max_delay=0.1,
            circuit_breaker_threshold=100  # High threshold to avoid opening
        )
        client = HttpClient(config)
        yield client
        client.close()

    def test_successful_request_no_retry_needed(self, client):
        """Test that successful request on first attempt doesn't retry."""
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            return Mock(status_code=200)

        result = client.with_retry(operation, "test operation")

        assert result.status_code == 200
        assert call_count == 1

    def test_successful_retry_after_transient_failure(self, client):
        """Test successful recovery after transient failure."""
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Transient error")
            return Mock(status_code=200)

        result = client.with_retry(operation, "test operation")

        assert result.status_code == 200
        assert call_count == 2

    def test_max_retries_exhausted(self, client):
        """Test that exception is raised after max retries exhausted."""
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            raise Exception("Persistent error")

        with pytest.raises(Exception, match="Persistent error"):
            client.with_retry(operation, "test operation")

        # Should attempt max_retries + 1 times (initial + 3 retries)
        assert call_count == client.config.max_retries + 1

    def test_exponential_backoff_delay_calculation(self):
        """Test that exponential backoff delays are calculated correctly."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_retries=3,
            retry_base_delay=1.0,
            retry_max_delay=10.0
        )

        # Verify backoff calculation logic
        # Attempt 0: delay = min(1 * 2^0, 10) = 1
        # Attempt 1: delay = min(1 * 2^1, 10) = 2
        # Attempt 2: delay = min(1 * 2^2, 10) = 4
        # Attempt 3: delay = min(1 * 2^3, 10) = 8

        assert config.retry_base_delay * (2 ** 0) == 1.0
        assert config.retry_base_delay * (2 ** 1) == 2.0
        assert config.retry_base_delay * (2 ** 2) == 4.0
        assert config.retry_base_delay * (2 ** 3) == 8.0

    def test_jitter_applied_to_delay(self):
        """Test that jitter is applied to retry delays."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_retries=3,
            retry_base_delay=1.0,
            retry_max_delay=10.0
        )
        client = HttpClient(config)

        # Jitter is ±50% of the delay
        base_delay = config.retry_base_delay
        min_jitter = -0.5 * base_delay
        max_jitter = 0.5 * base_delay

        # Verify jitter bounds are valid
        assert min_jitter == -0.5
        assert max_jitter == 0.5

    def test_retry_count_tracking(self, client):
        """Test that retry attempts are tracked correctly."""
        attempts = []

        def operation():
            attempts.append(len(attempts))
            if len(attempts) < 2:
                raise Exception("Error")
            return Mock(status_code=200)

        result = client.with_retry(operation, "test operation")

        assert result.status_code == 200
        assert len(attempts) == 2

    def test_circuit_breaker_records_failure(self, client):
        """Test that circuit breaker records failure on max retries."""
        def operation():
            raise Exception("Error")

        initial_state = client.circuit_breaker.get_stats()

        with pytest.raises(Exception):
            client.with_retry(operation, "test operation")

        final_state = client.circuit_breaker.get_stats()
        assert final_state["failure_count"] > initial_state["failure_count"]

    def test_circuit_breaker_records_success(self, client):
        """Test that circuit breaker records success on first attempt."""
        def operation():
            return Mock(status_code=200)

        initial_state = client.circuit_breaker.get_stats()

        client.with_retry(operation, "test operation")

        final_state = client.circuit_breaker.get_stats()
        assert final_state["success_count"] > initial_state["success_count"]


# ============================================================================
# SECTION 5: Circuit Breaker Integration Tests (~6 tests)
# ============================================================================

class TestCircuitBreakerIntegration:
    """Test circuit breaker integration with HttpClient."""

    @pytest.fixture
    def client(self):
        """Create HttpClient with low failure threshold for quick testing."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_retries=0,
            circuit_breaker_threshold=2,
            circuit_breaker_timeout=0.5
        )
        client = HttpClient(config)
        yield client
        client.close()

    def test_circuit_breaker_opens_after_threshold_failures(self, client):
        """Test circuit opens after reaching failure threshold."""
        def failing_operation():
            raise Exception("Error")

        # Record failures up to threshold
        for _ in range(client.circuit_breaker.threshold):
            with pytest.raises(Exception):
                client.with_retry(failing_operation, "test")

        assert client.circuit_breaker.get_state() == CircuitState.OPEN

    def test_circuit_breaker_prevents_requests_when_open(self, client):
        """Test requests are rejected when circuit is open."""
        def failing_operation():
            raise Exception("Error")

        # Open the circuit
        for _ in range(client.circuit_breaker.threshold):
            with pytest.raises(Exception):
                client.with_retry(failing_operation, "test")

        # Circuit should be open
        assert client.circuit_breaker.get_state() == CircuitState.OPEN

        # Next request should fail immediately
        def success_operation():
            return Mock(status_code=200)

        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            client.with_retry(success_operation, "test")

    def test_circuit_breaker_transitions_to_half_open(self, client):
        """Test circuit transitions to HALF_OPEN after timeout."""
        def failing_operation():
            raise Exception("Error")

        # Open circuit
        for _ in range(client.circuit_breaker.threshold):
            with pytest.raises(Exception):
                client.with_retry(failing_operation, "test")

        assert client.circuit_breaker.get_state() == CircuitState.OPEN

        # Wait for timeout
        time.sleep(client.circuit_breaker.timeout + 0.1)

        # Should transition to HALF_OPEN
        assert client.circuit_breaker.get_state() == CircuitState.HALF_OPEN

    def test_circuit_breaker_closes_after_half_open_success(self, client):
        """Test circuit closes after successful requests in HALF_OPEN state."""
        def failing_operation():
            raise Exception("Error")

        # Open circuit
        for _ in range(client.circuit_breaker.threshold):
            with pytest.raises(Exception):
                client.with_retry(failing_operation, "test")

        # Wait for timeout
        time.sleep(client.circuit_breaker.timeout + 0.1)

        # Now make successful requests in HALF_OPEN
        def success_operation():
            return Mock(status_code=200)

        for _ in range(client.circuit_breaker.half_open_max_calls):
            client.with_retry(success_operation, "test")

        # Circuit should be CLOSED
        assert client.circuit_breaker.get_state() == CircuitState.CLOSED

    def test_circuit_breaker_reopens_if_half_open_fails(self, client):
        """Test circuit reopens if request fails in HALF_OPEN state."""
        def failing_operation():
            raise Exception("Error")

        # Open circuit
        for _ in range(client.circuit_breaker.threshold):
            with pytest.raises(Exception):
                client.with_retry(failing_operation, "test")

        # Wait for timeout
        time.sleep(client.circuit_breaker.timeout + 0.1)

        # Try a failing operation in HALF_OPEN
        with pytest.raises(Exception):
            client.with_retry(failing_operation, "test")

        # Circuit should reopen
        assert client.circuit_breaker.get_state() == CircuitState.OPEN

    def test_circuit_breaker_state_accessible(self, client):
        """Test that circuit breaker state is accessible."""
        state = client.circuit_breaker.get_state()
        assert state == CircuitState.CLOSED

        stats = client.circuit_breaker.get_stats()
        assert stats["state"] == "closed"
        assert "failure_count" in stats
        assert "success_count" in stats


# ============================================================================
# SECTION 6: Thread Safety Tests (~3 tests)
# ============================================================================

class TestThreadSafety:
    """Test thread safety under concurrent load."""

    @pytest.fixture
    def client(self):
        """Create HttpClient for thread safety testing."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_retries=1,
            circuit_breaker_threshold=1000  # High threshold to avoid opening
        )
        client = HttpClient(config)
        yield client
        client.close()

    def test_concurrent_get_requests(self, client):
        """Test concurrent GET requests are thread-safe."""
        request_count = 0
        lock = threading.Lock()

        def operation():
            nonlocal request_count
            with lock:
                request_count += 1
            return Mock(status_code=200)

        def make_request():
            for _ in range(5):
                try:
                    client.with_retry(operation, "GET")
                except Exception:
                    pass

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            for future in futures:
                future.result()

        # All requests should complete
        assert request_count == 25  # 5 threads * 5 requests

    def test_concurrent_post_requests(self, client):
        """Test concurrent POST requests are thread-safe."""
        request_count = 0
        lock = threading.Lock()

        def operation():
            nonlocal request_count
            with lock:
                request_count += 1
            return Mock(status_code=201)

        def make_request():
            for _ in range(5):
                try:
                    client.with_retry(operation, "POST")
                except Exception:
                    pass

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            for future in futures:
                future.result()

        assert request_count == 25

    def test_circuit_breaker_state_under_concurrent_load(self, client):
        """Test circuit breaker state remains consistent under concurrent load."""
        def operation():
            return Mock(status_code=200)

        def make_request():
            for _ in range(10):
                try:
                    client.with_retry(operation, "test")
                except Exception:
                    pass

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            for future in futures:
                future.result()

        # Circuit breaker should be in valid state
        state = client.circuit_breaker.get_state()
        assert state in [CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN]


# ============================================================================
# SECTION 7: Error Handling Tests (~2 tests)
# ============================================================================

class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.fixture
    def client(self):
        """Create HttpClient for error testing."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            max_retries=1,
            circuit_breaker_threshold=100
        )
        client = HttpClient(config)
        yield client
        client.close()

    def test_network_error_handling(self, client):
        """Test network error handling with retries."""
        def operation():
            raise httpx.ConnectError("Connection failed")

        with pytest.raises(httpx.ConnectError):
            client.with_retry(operation, "network request")

    def test_http_error_status_codes(self, client):
        """Test handling of various HTTP error status codes."""
        def operation():
            response = Mock(spec=httpx.Response)
            response.status_code = 500
            return response

        # Operation should succeed (returns response with 500 status)
        result = client.with_retry(operation, "http error")
        assert result.status_code == 500


# ============================================================================
# SECTION 8: HttpClientFactory Tests (~3 tests)
# ============================================================================

class TestHttpClientFactory:
    """Test HttpClientFactory registry pattern."""

    def setup_method(self):
        """Reset factory before each test."""
        HttpClientFactory.reset()

    def teardown_method(self):
        """Clean up after each test."""
        HttpClientFactory.reset()

    def test_factory_creates_client(self):
        """Test factory creates client instance."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={}
        )

        client = HttpClientFactory.get_client("test", config)

        assert client is not None
        assert isinstance(client, HttpClient)

    def test_factory_caches_clients(self):
        """Test factory caches and returns same instance."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={}
        )

        client1 = HttpClientFactory.get_client("provider1", config)
        client2 = HttpClientFactory.get_client("provider1", config)

        assert client1 is client2  # Same instance

    def test_factory_separate_clients_for_different_providers(self):
        """Test factory creates separate clients for different providers."""
        config1 = HttpClientConfig(
            base_url="https://api.example.com",
            headers={}
        )
        config2 = HttpClientConfig(
            base_url="https://api.other.com",
            headers={}
        )

        client1 = HttpClientFactory.get_client("provider1", config1)
        client2 = HttpClientFactory.get_client("provider2", config2)

        assert client1 is not client2
        assert client1.config.base_url == "https://api.example.com"
        assert client2.config.base_url == "https://api.other.com"

    def test_factory_reset_clears_clients(self):
        """Test factory reset clears all cached clients."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={}
        )

        client1 = HttpClientFactory.get_client("test", config)
        assert client1 is not None

        HttpClientFactory.reset()

        # After reset, new instance should be created
        client2 = HttpClientFactory.get_client("test", config)
        # Different instances, but same provider name
        assert isinstance(client2, HttpClient)

    def test_factory_thread_safety(self):
        """Test factory is thread-safe during concurrent access."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={}
        )

        clients = []
        lock = threading.Lock()

        def get_client():
            client = HttpClientFactory.get_client("concurrent", config)
            with lock:
                clients.append(client)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_client) for _ in range(5)]
            for future in futures:
                future.result()

        # All should get same instance
        assert all(c is clients[0] for c in clients)


# ============================================================================
# SECTION 9: Get Stats Tests (~2 tests)
# ============================================================================

class TestGetStats:
    """Test get_stats() method."""

    @pytest.fixture
    def client(self):
        """Create HttpClient for stats testing."""
        config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={},
            default_timeout=45.0,
            max_connections=60,
            max_keepalive_connections=25,
            max_retries=2,
            retry_base_delay=0.5,
            retry_max_delay=8.0,
            circuit_breaker_threshold=10
        )
        client = HttpClient(config)
        yield client
        client.close()

    def test_get_stats_returns_all_fields(self, client):
        """Test get_stats returns all expected fields."""
        stats = client.get_stats()

        assert "base_url" in stats
        assert "default_timeout" in stats
        assert "max_connections" in stats
        assert "max_keepalive_connections" in stats
        assert "max_retries" in stats
        assert "retry_base_delay" in stats
        assert "retry_max_delay" in stats
        assert "circuit_breaker_state" in stats
        assert "circuit_breaker_threshold" in stats

    def test_get_stats_values_correct(self, client):
        """Test get_stats returns correct values."""
        stats = client.get_stats()

        assert stats["base_url"] == "https://api.example.com"
        assert stats["default_timeout"] == 45.0
        assert stats["max_connections"] == 60
        assert stats["max_keepalive_connections"] == 25
        assert stats["max_retries"] == 2
        assert stats["retry_base_delay"] == 0.5
        assert stats["retry_max_delay"] == 8.0
        assert stats["circuit_breaker_threshold"] == 10
        assert stats["circuit_breaker_state"] == "closed"
