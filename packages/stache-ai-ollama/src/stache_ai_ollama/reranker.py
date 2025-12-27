"""Ollama reranker provider using BGE reranker models"""

import logging
from typing import List, Dict, Any

from stache_ai.providers.reranker import RerankerProvider
from stache_ai.config import Settings
from .client import OllamaClient

logger = logging.getLogger(__name__)


class OllamaReranker(RerankerProvider):
    """
    Reranker using Ollama with BGE reranker models.

    Requires pulling a reranker model first:
        ollama pull qllama/bge-reranker-v2-m3

    Or for smaller model:
        ollama pull qllama/bge-reranker-large
    """

    def __init__(
        self,
        config: Settings,
        model: str = "qllama/bge-reranker-v2-m3"
    ):
        """
        Initialize Ollama reranker.

        Args:
            config: Settings instance with Ollama configuration
            model: Reranker model name (default: qllama/bge-reranker-v2-m3)
        """
        self.client = OllamaClient(config)
        self.model = model
        self.base_url = self.client.base_url
        logger.info(f"Initialized Ollama reranker with model {model} at {self.base_url}")

    def _get_relevance_score(self, query: str, document: str) -> float:
        """
        Get relevance score for a query-document pair.

        BGE rerankers expect input in format: query + document
        and return a score indicating relevance.
        """
        # BGE reranker models use the generate endpoint with a specific prompt format
        # The model outputs "yes" or "no" with logprobs, or a relevance score
        prompt = f"Query: {query}\nDocument: {document}\nIs this document relevant to the query?"

        try:
            response = self.client.post(
                "/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": 1,  # We just need a score
                    }
                },
                timeout=self.client.default_timeout
            )
            response.raise_for_status()
            result = response.json()

            # The response text from BGE reranker models typically contains a score
            # or we can use the generation as a proxy
            response_text = result.get("response", "").strip().lower()

            # Try to parse as float first (some models output scores directly)
            try:
                return float(response_text)
            except ValueError:
                pass

            # Fallback: interpret yes/no responses
            if response_text.startswith("yes"):
                return 0.9
            elif response_text.startswith("no"):
                return 0.1
            else:
                # Use embedding similarity as fallback
                return 0.5

        except Exception as e:
            logger.warning(f"Failed to get relevance score: {e}")
            return 0.5

    def _batch_rerank(self, query: str, documents: List[str]) -> List[float]:
        """
        Batch rerank using embeddings similarity.

        This is more efficient than individual scoring for Ollama.
        """
        try:
            # Get query embedding
            query_resp = self.client.post(
                "/api/embeddings",
                json={"model": self.model, "prompt": f"query: {query}"},
                timeout=self.client.default_timeout
            )
            query_resp.raise_for_status()
            query_embedding = query_resp.json().get("embedding", [])

            scores = []
            for doc in documents:
                # Get document embedding
                doc_resp = self.client.post(
                    "/api/embeddings",
                    json={"model": self.model, "prompt": f"passage: {doc}"},
                    timeout=self.client.default_timeout
                )
                doc_resp.raise_for_status()
                doc_embedding = doc_resp.json().get("embedding", [])

                # Calculate cosine similarity
                if query_embedding and doc_embedding:
                    score = self._cosine_similarity(query_embedding, doc_embedding)
                    scores.append(score)
                else:
                    scores.append(0.5)

            return scores

        except Exception as e:
            logger.error(f"Batch rerank failed: {e}")
            return [0.5] * len(documents)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int | None = None
    ) -> List[Dict[str, Any]]:
        """Rerank results using Ollama BGE reranker"""
        if not results:
            return results

        documents = [r.get("text", "") for r in results]

        # Use batch embedding-based reranking (more reliable with Ollama)
        scores = self._batch_rerank(query, documents)

        # Combine with original scores and rebuild results
        reranked = []
        for i, (result, new_score) in enumerate(zip(results, scores)):
            updated = result.copy()
            original_score = result.get("score", 0.5)
            # Weighted combination: 60% rerank score, 40% original
            updated["score"] = 0.6 * new_score + 0.4 * original_score
            updated["_rerank_score"] = new_score
            updated["_original_score"] = original_score
            reranked.append(updated)

        # Sort by new score
        reranked.sort(key=lambda x: x["score"], reverse=True)

        if top_k:
            reranked = reranked[:top_k]

        logger.debug(f"Reranked {len(results)} results using Ollama")
        return reranked

    def get_name(self) -> str:
        return f"ollama/{self.model}"
