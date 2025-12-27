"""Comprehensive test suite for Mixedbread embedding provider.

Test coverage includes:
- Instantiation and configuration (~5 tests)
- Embedding generation (single and batch) (~8 tests)
- Error handling and resilience (~6 tests)
- Circuit breaker integration (~4 tests)
- Factory and isolation (~3 tests)
- Configuration and customization (~4 tests)

Total: ~30 tests
"""

import pytest
import httpx
from unittest.mock import Mock, patch, MagicMock
from stache_ai.config import Settings
from stache_ai_mixedbread.provider import (
    MixedbreadEmbeddingProvider,
    MIXEDBREAD_DIMENSIONS
)
from stache_ai.providers.resilience import CircuitState, HttpClientFactory


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def reset_http_client_factory():
    """Reset HttpClientFactory before and after each test.

    Ensures a clean state for each test and prevents state leakage.
    """
    HttpClientFactory.reset()
    yield
    HttpClientFactory.reset()


@pytest.fixture
def mock_settings():
    """Create test settings with Mixedbread configuration."""
    return Settings(
        mixedbread_api_key="test-api-key-12345",
        mixedbread_model="mxbai-embed-large-v1",
        mixedbread_timeout=60.0,
        mixedbread_max_retries=3,
        mixedbread_retry_base_delay=1.0,
        mixedbread_retry_max_delay=10.0,
        mixedbread_circuit_breaker_threshold=10,
        mixedbread_circuit_breaker_timeout=60.0,
        mixedbread_circuit_breaker_half_open_max_calls=3,
        mixedbread_max_connections=50,
        mixedbread_max_keepalive_connections=20,
        mixedbread_keepalive_expiry=30.0
    )


@pytest.fixture
def mock_embedding_response():
    """Create a mock API response with embeddings."""
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": [0.1] * 1024, "index": 0},
            {"object": "embedding", "embedding": [0.2] * 1024, "index": 1},
            {"object": "embedding", "embedding": [0.3] * 1024, "index": 2},
        ],
        "model": "mxbai-embed-large-v1",
        "usage": {"prompt_tokens": 10, "total_tokens": 10}
    }


# ============================================================================
# SECTION 1: Instantiation Tests (~5 tests)
# ============================================================================

class TestInstantiation:
    """Test MixedbreadEmbeddingProvider instantiation."""

    def test_provider_instantiation_with_valid_settings(self, mock_settings):
        """Test provider creation with valid settings."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        assert provider is not None
        assert isinstance(provider, MixedbreadEmbeddingProvider)
        assert provider.api_key == "test-api-key-12345"
        assert provider.model == "mxbai-embed-large-v1"

    def test_provider_api_key_configuration(self, mock_settings):
        """Test API key is correctly configured from settings."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        assert provider.api_key == mock_settings.mixedbread_api_key
        assert provider.api_key is not None

    def test_provider_http_client_obtained_from_factory(self, mock_settings):
        """Test HttpClient is obtained from factory."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Verify client exists and is the expected type
        assert hasattr(provider, "_client")
        assert provider._client is not None
        from stache_ai.providers.resilience.http_client import HttpClient
        assert isinstance(provider._client, HttpClient)

    def test_provider_requires_api_key(self):
        """Test that provider raises error when API key is missing."""
        settings = Settings(mixedbread_api_key=None)

        with pytest.raises(ValueError, match="MIXEDBREAD_API_KEY is required"):
            MixedbreadEmbeddingProvider(settings)

    def test_provider_base_url_is_set(self, mock_settings):
        """Test that base URL is correctly set."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        assert provider.base_url == "https://api.mixedbread.ai"


# ============================================================================
# SECTION 2: Embedding Generation Tests (~8 tests)
# ============================================================================

class TestEmbeddingGeneration:
    """Test embedding generation functionality."""

    def test_single_embedding_generation(self, mock_settings, mock_embedding_response):
        """Test successful single embedding generation."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Mock the _sync_client.post method via _client
        mock_response = MagicMock()
        mock_response.json.return_value = mock_embedding_response
        provider._client._sync_client.post = Mock(return_value=mock_response)

        embedding = provider.embed("test text")

        assert embedding is not None
        assert isinstance(embedding, list)
        assert len(embedding) == 1024
        assert all(isinstance(x, (int, float)) for x in embedding)

    def test_batch_embedding_generation(self, mock_settings, mock_embedding_response):
        """Test batch embedding generation."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Mock the _sync_client.post method
        mock_response = MagicMock()
        mock_response.json.return_value = mock_embedding_response
        provider._client._sync_client.post = Mock(return_value=mock_response)

        embeddings = provider.embed_batch(["text1", "text2", "text3"])

        assert embeddings is not None
        assert isinstance(embeddings, list)
        assert len(embeddings) == 3
        for embedding in embeddings:
            assert len(embedding) == 1024

    def test_embedding_dimensions_match_expected(self, mock_settings):
        """Test embedding dimensions match expected value."""
        provider = MixedbreadEmbeddingProvider(mock_settings)
        dimensions = provider.get_dimensions()

        assert dimensions == 1024

    def test_embedding_normalization_applied(self, mock_settings):
        """Test that normalized=True is sent to API."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1] * 1024}],
            "model": "mxbai-embed-large-v1"
        }
        provider._client._sync_client.post = Mock(return_value=mock_response)

        provider.embed("test")

        # Verify API was called with normalized=True
        call_args = provider._client._sync_client.post.call_args
        json_payload = call_args[1]["json"]
        assert json_payload["normalized"] is True

    def test_model_name_in_api_request(self, mock_settings):
        """Test that configured model name is sent to API."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1] * 1024}],
            "model": "mxbai-embed-large-v1"
        }
        provider._client._sync_client.post = Mock(return_value=mock_response)

        provider.embed("test")

        # Verify model name was sent correctly
        call_args = provider._client._sync_client.post.call_args
        json_payload = call_args[1]["json"]
        assert json_payload["model"] == "mxbai-embed-large-v1"

    def test_empty_input_handling(self, mock_settings):
        """Test handling of empty input."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [], "model": "mxbai-embed-large-v1"}
        provider._client._sync_client.post = Mock(return_value=mock_response)

        # Empty string should raise IndexError when trying to access result[0]
        with pytest.raises(IndexError):
            provider.embed("")

    def test_authorization_header_present(self, mock_settings, mock_embedding_response):
        """Test that Authorization header is correctly set in HttpClient config."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Verify Authorization header is in the client's headers
        assert "Authorization" in provider._client.config.headers
        assert provider._client.config.headers["Authorization"] == f"Bearer {mock_settings.mixedbread_api_key}"


# ============================================================================
# SECTION 3: Error Handling Tests (~6 tests)
# ============================================================================

class TestErrorHandling:
    """Test error handling and resilience."""

    def test_authentication_failure_401(self, mock_settings):
        """Test API authentication failure (401)."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock()
        )
        provider._client._sync_client.post = Mock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            provider.embed("test")

    def test_rate_limiting_429(self, mock_settings):
        """Test rate limiting response (429)."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=MagicMock()
        )
        provider._client._sync_client.post = Mock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            provider.embed("test")

    def test_invalid_input_error(self, mock_settings):
        """Test handling of invalid input error."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=MagicMock()
        )
        provider._client._sync_client.post = Mock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            provider.embed("test")

    def test_network_timeout(self, mock_settings):
        """Test network timeout handling."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        provider._client._sync_client.post = Mock(side_effect=httpx.ConnectError("Connection timeout"))

        with pytest.raises(httpx.ConnectError):
            provider.embed("test")

    def test_malformed_response(self, mock_settings):
        """Test malformed API response handling."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        # Missing "data" field in response
        mock_response.json.return_value = {"model": "mxbai-embed-large-v1"}
        provider._client._sync_client.post = Mock(return_value=mock_response)

        with pytest.raises(KeyError):
            provider.embed("test")

    def test_server_error_500(self, mock_settings):
        """Test server error (500) handling."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock()
        )
        provider._client._sync_client.post = Mock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            provider.embed("test")


# ============================================================================
# SECTION 4: Model Dimensions Tests (~4 tests)
# ============================================================================

class TestModelDimensions:
    """Test model dimensions mapping."""

    def test_default_model_dimensions(self, mock_settings):
        """Test default model dimensions for mxbai-embed-large-v1."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        assert provider.get_dimensions() == 1024

    def test_model_variant_dimensions(self):
        """Test dimensions for model variant."""
        settings = Settings(
            mixedbread_api_key="test-key",
            mixedbread_model="mxbai-embed-2d-large-v1"
        )
        provider = MixedbreadEmbeddingProvider(settings)

        assert provider.get_dimensions() == 1024

    def test_unknown_model_defaults_to_1024(self):
        """Test unknown model defaults to 1024 dimensions."""
        settings = Settings(
            mixedbread_api_key="test-key",
            mixedbread_model="unknown-model-v1"
        )
        provider = MixedbreadEmbeddingProvider(settings)

        # Should default to 1024
        assert provider.get_dimensions() == 1024

    def test_all_known_models_have_dimensions(self):
        """Test all known models have correct dimension mapping."""
        for model_name, expected_dims in MIXEDBREAD_DIMENSIONS.items():
            settings = Settings(
                mixedbread_api_key="test-key",
                mixedbread_model=model_name
            )
            provider = MixedbreadEmbeddingProvider(settings)

            assert provider.get_dimensions() == expected_dims


# ============================================================================
# SECTION 5: Provider Name Tests (~2 tests)
# ============================================================================

class TestProviderName:
    """Test provider naming."""

    def test_provider_name_includes_model(self, mock_settings):
        """Test provider name includes model identifier."""
        provider = MixedbreadEmbeddingProvider(mock_settings)
        name = provider.get_name()

        assert "mixedbread" in name.lower()
        assert "mxbai-embed-large-v1" in name

    def test_provider_name_format(self, mock_settings):
        """Test provider name follows expected format."""
        provider = MixedbreadEmbeddingProvider(mock_settings)
        name = provider.get_name()

        # Should be in format "mixedbread/model-name"
        assert name.startswith("mixedbread/")


# ============================================================================
# SECTION 6: Configuration and Settings Tests (~4 tests)
# ============================================================================

class TestConfigurationSettings:
    """Test configuration from settings."""

    def test_custom_timeout_setting(self):
        """Test custom timeout configuration from settings."""
        settings = Settings(
            mixedbread_api_key="test-key",
            mixedbread_timeout=120.0
        )
        provider = MixedbreadEmbeddingProvider(settings)

        # Verify timeout is passed to HttpClient config
        assert provider._client.config.default_timeout == 120.0

    def test_custom_model_setting(self):
        """Test custom model configuration."""
        settings = Settings(
            mixedbread_api_key="test-key",
            mixedbread_model="mxbai-embed-2d-large-v1"
        )
        provider = MixedbreadEmbeddingProvider(settings)

        assert provider.model == "mxbai-embed-2d-large-v1"

    def test_multiple_providers_independent_instances(self, mock_settings):
        """Test multiple provider instances are independent."""
        provider1 = MixedbreadEmbeddingProvider(mock_settings)
        provider2 = MixedbreadEmbeddingProvider(mock_settings)

        # Should be different instances
        assert provider1 is not provider2

    def test_settings_preserved_after_instantiation(self, mock_settings):
        """Test that settings are correctly stored in provider."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        assert provider.settings == mock_settings
        assert provider.api_key == mock_settings.mixedbread_api_key
        assert provider.model == mock_settings.mixedbread_model


# ============================================================================
# SECTION 7: API Endpoint Tests (~2 tests)
# ============================================================================

class TestAPIEndpoint:
    """Test API endpoint configuration."""

    def test_correct_endpoint_called(self, mock_settings, mock_embedding_response):
        """Test that correct API endpoint is called."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.json.return_value = mock_embedding_response
        provider._client._sync_client.post = Mock(return_value=mock_response)

        provider.embed("test")

        # Verify correct endpoint
        call_args = provider._client._sync_client.post.call_args
        endpoint = call_args[0][0]
        assert endpoint == "/v1/embeddings"

    def test_base_url_correctly_configured(self, mock_settings):
        """Test that base URL is correctly configured in HttpClient."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Verify base URL is set in HttpClient config
        assert provider._client.config.base_url == "https://api.mixedbread.ai"


# ============================================================================
# SECTION 8: Batch Operation Tests (~2 tests)
# ============================================================================

class TestBatchOperations:
    """Test batch operation handling."""

    def test_batch_request_format(self, mock_settings, mock_embedding_response):
        """Test batch request is formatted correctly."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.json.return_value = mock_embedding_response
        provider._client._sync_client.post = Mock(return_value=mock_response)

        texts = ["text1", "text2", "text3"]
        provider.embed_batch(texts)

        # Verify batch request format
        call_args = provider._client._sync_client.post.call_args
        json_payload = call_args[1]["json"]
        assert json_payload["input"] == texts
        assert json_payload["model"] == "mxbai-embed-large-v1"

    def test_batch_results_order_preserved(self, mock_settings):
        """Test that batch results order matches input order."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        embeddings_data = [
            {"embedding": [0.1] * 1024, "index": 0},
            {"embedding": [0.2] * 1024, "index": 1},
            {"embedding": [0.3] * 1024, "index": 2},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": embeddings_data,
            "model": "mxbai-embed-large-v1"
        }
        provider._client._sync_client.post = Mock(return_value=mock_response)

        embeddings = provider.embed_batch(["text1", "text2", "text3"])

        # Verify order is preserved
        assert embeddings[0][0] == 0.1  # First element first batch
        assert embeddings[1][0] == 0.2  # First element second batch
        assert embeddings[2][0] == 0.3  # First element third batch


# ============================================================================
# SECTION 4: Circuit Breaker Integration Tests (~4 tests)
# ============================================================================

class TestCircuitBreakerIntegration:
    """Test circuit breaker integration."""

    def test_circuit_breaker_reference_is_set(self, mock_settings):
        """Test that circuit breaker reference is set from HttpClient."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        assert provider.circuit_breaker is not None
        assert provider.circuit_breaker is provider._client.circuit_breaker

    def test_circuit_breaker_state_accessible(self, mock_settings):
        """Test circuit breaker state is accessible."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Should start in CLOSED state
        assert provider.circuit_breaker.get_state() == CircuitState.CLOSED

    def test_circuit_breaker_threshold_from_settings(self, mock_settings):
        """Test circuit breaker threshold is configured from settings."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Verify threshold matches settings
        assert provider.circuit_breaker.threshold == mock_settings.mixedbread_circuit_breaker_threshold

    def test_circuit_breaker_timeout_from_settings(self, mock_settings):
        """Test circuit breaker timeout is configured from settings."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        # Verify timeout matches settings
        assert provider.circuit_breaker.timeout == mock_settings.mixedbread_circuit_breaker_timeout


# ============================================================================
# SECTION 5: Factory Integration Tests (~3 tests)
# ============================================================================

class TestFactoryIntegration:
    """Test HttpClientFactory integration."""

    def test_multiple_instances_share_same_http_client(self, mock_settings):
        """Test that multiple Mixedbread instances share the same HttpClient."""
        provider1 = MixedbreadEmbeddingProvider(mock_settings)
        provider2 = MixedbreadEmbeddingProvider(mock_settings)

        # Should use the same cached HttpClient from factory
        assert provider1._client is provider2._client

    def test_factory_reset_clears_cached_client(self, mock_settings):
        """Test that factory reset clears cached client."""
        provider1 = MixedbreadEmbeddingProvider(mock_settings)
        client1 = provider1._client

        # Reset factory
        HttpClientFactory.reset()

        # Create new provider - should get new client
        provider2 = MixedbreadEmbeddingProvider(mock_settings)
        client2 = provider2._client

        # Should be different clients
        assert client1 is not client2

    def test_factory_isolation_from_other_providers(self, mock_settings):
        """Test factory isolation between different providers."""
        # Create Mixedbread provider
        mb_settings = mock_settings
        mb_provider = MixedbreadEmbeddingProvider(mb_settings)
        mb_client = mb_provider._client

        # Create another Mixedbread provider with different name via direct factory call
        from stache_ai.providers.resilience.http_client import HttpClientConfig
        other_config = HttpClientConfig(
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer other-key"}
        )
        other_client = HttpClientFactory.get_client("other-provider", other_config)

        # Should be different clients
        assert mb_client is not other_client


# ============================================================================
# SECTION 9: Error Logging Tests (~2 tests)
# ============================================================================

class TestErrorLogging:
    """Test error logging behavior."""

    @patch('stache_ai_mixedbread.provider.logger')
    @patch('httpx.post')
    def test_single_embedding_error_logged(self, mock_post, mock_logger, mock_settings):
        """Test that single embedding errors are logged."""
        mock_post.side_effect = Exception("API Error")

        provider = MixedbreadEmbeddingProvider(mock_settings)

        with pytest.raises(Exception):
            provider.embed("test")

        # Verify error was logged
        mock_logger.error.assert_called()

    @patch('stache_ai_mixedbread.provider.logger')
    @patch('httpx.post')
    def test_batch_embedding_error_logged(self, mock_post, mock_logger, mock_settings):
        """Test that batch embedding errors are logged."""
        mock_post.side_effect = Exception("API Error")

        provider = MixedbreadEmbeddingProvider(mock_settings)

        with pytest.raises(Exception):
            provider.embed_batch(["test1", "test2"])

        # Verify error was logged
        mock_logger.error.assert_called()


# ============================================================================
# SECTION 10: Edge Cases and Special Scenarios (~3 tests)
# ============================================================================

class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_large_batch_handling(self, mock_settings):
        """Test handling of large batch requests."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        large_batch = ["text"] * 100
        embeddings_response = {
            "data": [{"embedding": [0.1] * 1024, "index": i} for i in range(100)],
            "model": "mxbai-embed-large-v1"
        }
        mock_response = MagicMock()
        mock_response.json.return_value = embeddings_response
        provider._client._sync_client.post = Mock(return_value=mock_response)

        embeddings = provider.embed_batch(large_batch)

        assert len(embeddings) == 100

    def test_unicode_text_handling(self, mock_settings, mock_embedding_response):
        """Test handling of unicode text."""
        provider = MixedbreadEmbeddingProvider(mock_settings)

        mock_response = MagicMock()
        mock_response.json.return_value = mock_embedding_response
        provider._client._sync_client.post = Mock(return_value=mock_response)

        unicode_text = "こんにちは世界 🌍 مرحبا بالعالم"
        embedding = provider.embed(unicode_text)

        # Should handle unicode without error
        assert embedding is not None
        assert len(embedding) == 1024

    def test_special_characters_in_api_key(self):
        """Test handling of special characters in API key."""
        special_key = "sk-test_key.with-special/chars+symbols="
        settings = Settings(
            mixedbread_api_key=special_key,
            mixedbread_model="mxbai-embed-large-v1"
        )
        provider = MixedbreadEmbeddingProvider(settings)

        assert provider.api_key == special_key
