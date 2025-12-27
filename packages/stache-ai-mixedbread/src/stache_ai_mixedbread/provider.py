"""Mixedbread embedding provider"""

from typing import List
import logging

from stache_ai.providers.base import EmbeddingProvider
from stache_ai.providers.resilience.http_client import HttpClientFactory, HttpClientConfig
from stache_ai.config import Settings

logger = logging.getLogger(__name__)

# Model dimensions
MIXEDBREAD_DIMENSIONS = {
    "mxbai-embed-large-v1": 1024,
    "mixedbread-ai/mxbai-embed-large-v1": 1024,
    "deepset-mxbai-embed-de-large-v1": 1024,
    "mxbai-embed-2d-large-v1": 1024,
}


class MixedbreadEmbeddingProvider(EmbeddingProvider):
    """Mixedbread embedding provider (mixedbread.ai API)"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.mixedbread_api_key
        self.model = settings.mixedbread_model
        self.base_url = "https://api.mixedbread.ai"
        self._dimensions = MIXEDBREAD_DIMENSIONS.get(self.model, 1024)

        if not self.api_key:
            raise ValueError("MIXEDBREAD_API_KEY is required for Mixedbread provider")

        # Create HttpClientConfig from settings
        http_config = HttpClientConfig(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            default_timeout=settings.mixedbread_timeout,
            max_retries=settings.mixedbread_max_retries,
            retry_base_delay=settings.mixedbread_retry_base_delay,
            retry_max_delay=settings.mixedbread_retry_max_delay,
            circuit_breaker_threshold=settings.mixedbread_circuit_breaker_threshold,
            circuit_breaker_timeout=settings.mixedbread_circuit_breaker_timeout,
            max_connections=settings.mixedbread_max_connections,
            max_keepalive_connections=settings.mixedbread_max_keepalive_connections,
        )

        # Get shared HttpClient from factory
        self._client = HttpClientFactory.get_client("mixedbread", http_config)
        self.circuit_breaker = self._client.circuit_breaker

        logger.info(
            f"MixedbreadEmbeddingProvider initialized successfully. "
            f"Model: {self.model}, "
            f"Dimensions: {self._dimensions}, "
            f"Max connections: {settings.mixedbread_max_connections}"
        )

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """Call Mixedbread embeddings API"""
        response = self._client.post(
            "/v1/embeddings",
            json={
                "model": self.model,
                "input": texts,
                "normalized": True,
            }
        )
        response.raise_for_status()
        data = response.json()

        # Extract embeddings from response
        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings

    def embed(self, text: str) -> List[float]:
        """Generate embedding for single text"""
        try:
            result = self._call_api([text])
            return result[0]
        except Exception as e:
            logger.error(f"Mixedbread embedding failed: {e}")
            raise

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            return self._call_api(texts)
        except Exception as e:
            logger.error(f"Mixedbread batch embedding failed: {e}")
            raise

    def get_dimensions(self) -> int:
        """Get embedding dimensions"""
        return self._dimensions

    def get_name(self) -> str:
        """Get provider name"""
        return f"mixedbread/{self.model}"
