"""Base class for reranker providers"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class RerankerProvider(ABC):
    """Abstract base class for reranking search results"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int | None = None
    ) -> List[Dict[str, Any]]:
        """
        Rerank search results based on query relevance.

        Args:
            query: The search query
            results: List of search results with 'text' and 'metadata' keys
            top_k: Optional limit on results to return (None = return all)

        Returns:
            Reranked list of results with updated scores
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get provider name"""
        pass
