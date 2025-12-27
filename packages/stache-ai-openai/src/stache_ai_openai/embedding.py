"""OpenAI embedding provider"""

from typing import List
from stache_ai.providers.base import EmbeddingProvider
from stache_ai.config import Settings
from openai import OpenAI


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider using text-embedding-3-small"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.get_embedding_model()
        self._dimensions = settings.embedding_dimension

    def embed(self, text: str) -> List[float]:
        """Generate embedding for single text"""
        response = self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        return [item.embedding for item in response.data]

    def get_dimensions(self) -> int:
        """Get embedding dimensions"""
        return self._dimensions
