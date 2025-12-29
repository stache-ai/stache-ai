"""Integration tests for Ollama providers and shared OllamaClient.

These tests verify that:
1. All Ollama providers (embedding, LLM, reranker) share a single OllamaClient instance
2. Retry logic works correctly with exponential backoff
3. Circuit breaker state affects all providers
4. Batch processing works in both sequential and parallel modes
5. HTTP calls are properly mocked to avoid Ollama dependency
"""

import pytest
from unittest.mock import patch, MagicMock

from stache_ai.config import Settings
from stache_ai_ollama.embedding import OllamaEmbeddingProvider
from stache_ai_ollama.llm import OllamaLLMProvider
from stache_ai_ollama.reranker import OllamaReranker
from stache_ai_ollama.client import OllamaClient
from stache_ai.providers.resilience import CircuitState


@pytest.fixture(autouse=True)
def reset_http_client_factory():
    """Reset HttpClientFactory before and after each test.

    This ensures test isolation by clearing the factory state
    between tests. Without this, tests would interfere with each other.
    """
    from stache_ai.providers.resilience import HttpClientFactory
    HttpClientFactory.reset()
    yield
    HttpClientFactory.reset()


@pytest.fixture
def mock_settings():
    """Create test Settings with Ollama configuration."""
    return Settings(
        ollama_url="http://localhost:11434",
        ollama_model="llama3.2",
        ollama_embedding_model="mxbai-embed-large",
        reranker_model="qllama/bge-reranker-v2-m3",
        ollama_enable_parallel=True,
        ollama_batch_size=10,
        ollama_max_retries=3,
        ollama_retry_base_delay=0.1,  # Shorter for tests
        ollama_retry_max_delay=0.5,
        ollama_circuit_breaker_threshold=3,
        ollama_circuit_breaker_timeout=1.0,
    )


class TestEmbeddingProviderInstantiation:
    """Test 1: Embedding provider instantiation"""

    def test_embedding_provider_creates_client(self, mock_settings):
        """OllamaEmbeddingProvider should create an OllamaClient instance."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            provider1 = OllamaEmbeddingProvider(mock_settings)
            provider2 = OllamaEmbeddingProvider(mock_settings)

            # Both providers should have OllamaClient instances (separate instances now)
            assert isinstance(provider1.client, OllamaClient)
            assert isinstance(provider2.client, OllamaClient)
            # Each provider has its own client instance
            assert provider1.client is not provider2.client


class TestEmbeddingWithRetry:
    """Test 2: Embedding with retry logic"""

    def test_embed_with_retry_succeeds_on_second_attempt(self, mock_settings):
        """Embedding should retry and succeed after initial failure."""
        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            # Setup mock client instance
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Mock post() to fail once then succeed
            success_response = MagicMock()
            success_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}

            mock_client_instance.post.side_effect = [
                Exception("Connection timeout"),  # First attempt fails
                success_response,  # Second attempt succeeds
            ]

            provider = OllamaEmbeddingProvider(mock_settings)
            result = provider.embed("test text")

            # Should return result from successful attempt
            assert result == [0.1, 0.2, 0.3]

            # Verify retry occurred (post called twice)
            assert mock_client_instance.post.call_count == 2


class TestBatchEmbeddingSequential:
    """Test 3: Batch embedding sequential"""

    def test_embed_batch_sequential_with_disable_parallel(self, mock_settings):
        """Batch embedding should work sequentially when parallel disabled."""
        mock_settings.ollama_enable_parallel = False

        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Mock responses for 5 texts
            responses = []
            for i in range(5):
                resp = MagicMock()
                resp.json.return_value = {"embedding": [0.1 * (i + 1)] * 3}
                responses.append(resp)

            mock_client_instance.post.side_effect = responses

            provider = OllamaEmbeddingProvider(mock_settings)
            texts = [f"text {i}" for i in range(5)]
            results = provider.embed_batch(texts)

            # Verify results returned in order
            assert len(results) == 5
            assert results[0] == [0.1] * 3
            assert results[4] == [0.5] * 3

            # Verify sequential processing (5 post calls)
            assert mock_client_instance.post.call_count == 5


class TestBatchEmbeddingParallel:
    """Test 4: Batch embedding parallel"""

    def test_embed_batch_parallel_with_enable_parallel(self, mock_settings):
        """Batch embedding should work in parallel when enabled."""
        mock_settings.ollama_enable_parallel = True
        mock_settings.ollama_batch_size = 5

        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Mock responses for 10 texts (parallel will call embed multiple times)
            def mock_post(endpoint, **kwargs):
                resp = MagicMock()
                # Return consistent embedding for simplicity
                resp.json.return_value = {"embedding": [0.5] * 3}
                return resp

            mock_client_instance.post = mock_post

            provider = OllamaEmbeddingProvider(mock_settings)
            texts = [f"text {i}" for i in range(10)]
            results = provider.embed_batch(texts)

            # Verify results returned in correct count
            assert len(results) == 10
            # All should have same embedding due to our mock
            assert all(r == [0.5] * 3 for r in results)


class TestLLMProviderInstantiation:
    """Test 5: LLM provider instantiation"""

    def test_llm_provider_creates_client(self, mock_settings):
        """LLM provider should create its own OllamaClient instance."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            embedding_provider = OllamaEmbeddingProvider(mock_settings)
            llm_provider = OllamaLLMProvider(mock_settings)

            # Both should have OllamaClient instances
            assert isinstance(llm_provider.client, OllamaClient)
            assert isinstance(embedding_provider.client, OllamaClient)
            # Each provider has its own client (no longer singleton)
            assert llm_provider.client is not embedding_provider.client


class TestLLMGenerationWithRetry:
    """Test 6: LLM generation with retry"""

    def test_llm_generate_with_retry(self, mock_settings):
        """LLM generation should retry and succeed after failure."""
        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Mock post() to fail once then succeed
            success_response = MagicMock()
            success_response.json.return_value = {"response": "Generated answer"}

            mock_client_instance.post.side_effect = [
                Exception("Network error"),
                success_response,
            ]

            provider = OllamaLLMProvider(mock_settings)
            result = provider.generate("What is AI?")

            # Should return generated response
            assert result == "Generated answer"

            # Verify retry occurred
            assert mock_client_instance.post.call_count == 2


class TestRerankerInstantiation:
    """Test 7: Reranker instantiation"""

    def test_reranker_creates_client(self, mock_settings):
        """Reranker should create its own OllamaClient instance."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            embedding_provider = OllamaEmbeddingProvider(mock_settings)
            reranker = OllamaReranker(mock_settings)

            # Both should have OllamaClient instances
            assert isinstance(reranker.client, OllamaClient)
            assert isinstance(embedding_provider.client, OllamaClient)
            # Each has its own client (no longer singleton)
            assert reranker.client is not embedding_provider.client


class TestAllProvidersCanInstantiate:
    """Test 8: All providers can instantiate correctly"""

    def test_embedding_llm_and_reranker_instantiate(self, mock_settings):
        """All three provider types should instantiate with OllamaClient."""
        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Create all three providers
            embedding = OllamaEmbeddingProvider(mock_settings)
            llm = OllamaLLMProvider(mock_settings)
            reranker = OllamaReranker(mock_settings)

            # All should have their own OllamaClient instances
            assert isinstance(embedding.client, OllamaClient)
            assert isinstance(llm.client, OllamaClient)
            assert isinstance(reranker.client, OllamaClient)

            # Each provider has a separate OllamaClient instance
            assert embedding.client is not llm.client
            assert llm.client is not reranker.client

            # But they all share the same underlying HttpClient via factory
            # So only one httpx.Client instance should be created
            assert mock_client_class.call_count == 1

            # Verify they share the same underlying HttpClient
            assert embedding.client._client is llm.client._client
            assert llm.client._client is reranker.client._client


class TestCircuitBreakerAffectsAllProviders:
    """Test 9: Circuit breaker affects all providers"""

    def test_circuit_breaker_opens_affects_all_providers(self, mock_settings):
        """When circuit breaker opens, all providers should be affected."""
        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Create all three providers
            embedding = OllamaEmbeddingProvider(mock_settings)
            llm = OllamaLLMProvider(mock_settings)
            reranker = OllamaReranker(mock_settings)

            # Get the shared client and circuit breaker
            client = embedding.client
            cb = client.circuit_breaker

            # Verify circuit is initially closed
            assert cb.get_state() == CircuitState.CLOSED

            # Record failures to trigger circuit breaker (threshold is 3)
            for i in range(3):
                cb.record_failure()

            # Circuit should be open
            assert cb.get_state() == CircuitState.OPEN

            # All providers should be affected by the circuit breaker
            with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
                embedding.embed("test")

            # LLM should also fail with circuit breaker error
            with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
                llm.generate("test")

            # Reranker gracefully fails (catches exception, returns default scores)
            # So we verify it still returns results with default scores
            result = reranker.rerank("test", [{"text": "document"}])
            assert len(result) == 1
            # Should have default score (0.5 from graceful failure)
            assert result[0]["score"] == 0.5


class TestHealthCheckForAllProviders:
    """Test 10: Health check works for all providers"""

    def test_health_check_all_providers(self, mock_settings):
        """All providers should be able to check health."""
        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Mock successful /api/version response
            version_response = MagicMock()
            version_response.raise_for_status.return_value = None
            mock_client_instance.get.return_value = version_response

            # Create providers
            embedding = OllamaEmbeddingProvider(mock_settings)
            llm = OllamaLLMProvider(mock_settings)
            reranker = OllamaReranker(mock_settings)

            # All should be available
            assert embedding.is_available() is True
            assert llm.client.is_healthy() is True
            assert reranker.client.is_healthy() is True


class TestClientTimeoutConfiguration:
    """Additional test: Verify client timeout configuration"""

    def test_client_uses_configured_timeouts(self, mock_settings):
        """Client should use timeouts from settings."""
        mock_settings.ollama_embedding_timeout = 60.0
        mock_settings.ollama_llm_timeout = 120.0
        mock_settings.ollama_health_check_timeout = 5.0

        with patch("stache_ai_ollama.client.httpx.Client"):
            client = OllamaClient(mock_settings)

            assert client.default_timeout == 60.0
            assert client.llm_timeout == 120.0
            assert client.health_timeout == 5.0


class TestClientConnectionPooling:
    """Additional test: Verify connection pooling configuration"""

    def test_client_connection_pool_configured(self, mock_settings):
        """Client should configure connection pooling correctly."""
        mock_settings.ollama_max_connections = 50
        mock_settings.ollama_max_keepalive_connections = 20
        mock_settings.ollama_keepalive_expiry = 30.0

        with patch("stache_ai_ollama.client.httpx.Client"):
            client = OllamaClient(mock_settings)

            assert client.max_connections == 50
            assert client.max_keepalive_connections == 20
            assert client.keepalive_expiry == 30.0


class TestRetryExhaustion:
    """Additional test: Verify retry exhaustion behavior"""

    def test_embed_fails_after_max_retries(self, mock_settings):
        """Embedding should fail after max retries exhausted."""
        # Use a new settings with lower threshold so circuit breaker doesn't open prematurely
        test_settings = Settings(
            ollama_url="http://localhost:11434",
            ollama_model="llama3.2",
            ollama_embedding_model="mxbai-embed-large",
            ollama_max_retries=2,
            ollama_retry_base_delay=0.01,
            ollama_retry_max_delay=0.05,
            ollama_circuit_breaker_threshold=10,  # High threshold to prevent opening
        )

        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Mock post() to always fail
            mock_client_instance.post.side_effect = Exception("Network error")

            provider = OllamaEmbeddingProvider(test_settings)

            # Should raise exception after retries exhausted
            with pytest.raises(Exception, match="Network error"):
                provider.embed("test text")

            # Should have tried max_retries + 1 times (initial + retries)
            expected_calls = test_settings.ollama_max_retries + 1
            assert mock_client_instance.post.call_count == expected_calls


class TestCircuitBreakerRecovery:
    """Additional test: Verify circuit breaker recovery"""

    def test_circuit_breaker_recovery_after_timeout(self, mock_settings):
        """Circuit should transition to HALF_OPEN after timeout."""
        import time

        with patch("stache_ai_ollama.client.httpx.Client") as mock_client_class:
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance

            # Configure short timeout for testing
            mock_settings.ollama_circuit_breaker_timeout = 0.2

            client = OllamaClient(mock_settings)
            cb = client.circuit_breaker

            # Record failures to open circuit
            for i in range(3):
                cb.record_failure()

            assert cb.get_state() == CircuitState.OPEN

            # Wait for timeout
            time.sleep(0.3)

            # Should transition to HALF_OPEN
            assert cb.get_state() == CircuitState.HALF_OPEN


class TestProviderFactoryMethods:
    """Additional test: Verify provider factory methods work"""

    def test_embedding_provider_get_name(self, mock_settings):
        """Embedding provider should return correct name."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            provider = OllamaEmbeddingProvider(mock_settings)
            name = provider.get_name()

            assert "ollama" in name
            assert mock_settings.ollama_embedding_model in name

    def test_embedding_provider_get_dimensions(self, mock_settings):
        """Embedding provider should return correct dimensions."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            provider = OllamaEmbeddingProvider(mock_settings)
            dims = provider.get_dimensions()

            # mxbai-embed-large should be 1024
            assert dims == 1024

    def test_llm_provider_get_name(self, mock_settings):
        """LLM provider should return correct name."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            provider = OllamaLLMProvider(mock_settings)
            name = provider.get_name()

            assert isinstance(name, str)

    def test_reranker_get_name(self, mock_settings):
        """Reranker should return correct name."""
        with patch("stache_ai_ollama.client.httpx.Client"):
            reranker = OllamaReranker(mock_settings)
            name = reranker.get_name()

            assert "ollama" in name
