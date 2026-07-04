"""Base class for reranker providers"""

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext


class RerankerProvider(ABC):
    """Abstract base class for reranking search results"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int | None = None,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """
        Rerank search results based on query relevance.

        Args:
            query: The search query
            results: List of search results with 'text' and 'metadata' keys
            top_k: Optional limit on results to return (None = return all)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Reranked list of results with updated scores
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get provider name"""
        pass
