"""Ollama embedding provider

Located in consolidated ollama directory for unified provider management.
"""

from typing import List
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from stache_ai.providers.base import EmbeddingProvider
from stache_ai.config import Settings
from .client import OllamaClient

logger = logging.getLogger(__name__)

# Known embedding model dimensions
OLLAMA_EMBEDDING_DIMENSIONS = {
    "mxbai-embed-large": 1024,
    "nomic-embed-text": 768,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
    "bge-large": 1024,
    "bge-m3": 1024,
}


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama embedding provider for local embeddings"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.ollama_embedding_model
        self._dimensions = OLLAMA_EMBEDDING_DIMENSIONS.get(
            self.model,
            settings.embedding_dimension
        )
        self.client = OllamaClient(settings)

        # Parallel processing config
        self.batch_size = settings.ollama_batch_size
        self.enable_parallel = settings.ollama_enable_parallel

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """Call Ollama embeddings API"""
        embeddings = []

        for text in texts:
            response = self.client.post(
                "/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.client.default_timeout
            )
            response.raise_for_status()
            data = response.json()
            embeddings.append(data["embedding"])

        return embeddings

    def _embed_single(self, text: str) -> List[float]:
        """Generate embedding for single text (internal helper)

        Args:
            text: Text to embed

        Returns:
            Embedding vector

        Raises:
            Exception: If embedding fails
        """
        result = self._call_api([text])
        return result[0]

    def embed(self, text: str) -> List[float]:
        """Generate embedding for single text

        Args:
            text: Text to embed

        Returns:
            Embedding vector

        Raises:
            Exception: If embedding fails
        """
        try:
            return self._embed_single(text)
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            raise

    def _embed_batch_sequential(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts sequentially

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (one per input text)

        Raises:
            RuntimeError: If embeddings fail
        """
        try:
            return self._call_api(texts)
        except Exception as e:
            logger.error(f"Ollama sequential batch embedding failed for {len(texts)} texts: {e}")
            raise

    def _embed_batch_parallel(self, texts: List[str]) -> List[List[float]]:
        """Embed batch in parallel with sub-batching to avoid overwhelming Ollama

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (one per input text, in original order)

        Raises:
            RuntimeError: If any embeddings fail
        """
        embeddings = [None] * len(texts)
        failed_indices = []
        failed_lock = Lock()  # Thread-safe lock for failed_indices

        logger.debug(f"Parallel embedding {len(texts)} texts (batch_size={self.batch_size})")

        # Process in sub-batches to avoid overwhelming Ollama
        for batch_start in range(0, len(texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(texts))
            batch_texts = texts[batch_start:batch_end]

            logger.debug(f"Processing sub-batch [{batch_start}:{batch_end}]")

            # Parallel processing within sub-batch
            with ThreadPoolExecutor(max_workers=self.batch_size) as executor:
                future_to_index = {
                    executor.submit(self.embed, text): i
                    for i, text in enumerate(batch_texts, start=batch_start)
                }

                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    try:
                        embeddings[index] = future.result()
                    except Exception as e:
                        logger.error(f"Failed to embed text at index {index}: {e}")
                        # Thread-safe append to failed_indices
                        with failed_lock:
                            failed_indices.append(index)

        if failed_indices:
            raise RuntimeError(
                f"Failed to embed {len(failed_indices)} texts at indices: {failed_indices}"
            )

        return embeddings

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts with optional parallelization

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (one per input text)

        Raises:
            RuntimeError: If any embeddings fail
        """
        try:
            if self.enable_parallel and len(texts) > 1:
                return self._embed_batch_parallel(texts)
            else:
                return self._embed_batch_sequential(texts)
        except Exception as e:
            logger.error(f"Ollama batch embedding failed for {len(texts)} texts: {e}")
            raise

    def get_dimensions(self) -> int:
        """Get embedding dimensions"""
        return self._dimensions

    def get_name(self) -> str:
        """Get provider name"""
        return f"ollama/{self.model}"

    def is_available(self) -> bool:
        """Check if Ollama is available"""
        return self.client.is_healthy()
