"""Cohere reranker provider"""

import logging
from typing import List, Dict, Any

from stache_ai.providers.reranker import RerankerProvider

logger = logging.getLogger(__name__)


class CohereReranker(RerankerProvider):
    """Reranker using Cohere's rerank API"""

    def __init__(self, api_key: str, model: str = "rerank-v3.5"):
        """
        Initialize Cohere reranker.

        Args:
            api_key: Cohere API key
            model: Rerank model to use (default: rerank-v3.5)
        """
        try:
            import cohere
            self.client = cohere.ClientV2(api_key=api_key)
            self.model = model
            logger.info(f"Initialized Cohere reranker with model {model}")
        except ImportError:
            raise ImportError("cohere package required: pip install cohere")

    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int | None = None
    ) -> List[Dict[str, Any]]:
        """Rerank results using Cohere"""
        if not results:
            return results

        # Extract documents for reranking
        documents = [r["text"] for r in results]

        try:
            response = self.client.rerank(
                query=query,
                documents=documents,
                model=self.model,
                top_n=top_k or len(results)
            )

            # Rebuild results in new order with updated scores
            reranked = []
            for item in response.results:
                original = results[item.index].copy()
                original["score"] = item.relevance_score
                original["original_index"] = item.index
                reranked.append(original)

            logger.debug(f"Reranked {len(results)} results to {len(reranked)}")
            return reranked

        except Exception as e:
            logger.error(f"Cohere rerank failed: {e}, returning original results")
            return results

    def get_name(self) -> str:
        return f"cohere/{self.model}"
