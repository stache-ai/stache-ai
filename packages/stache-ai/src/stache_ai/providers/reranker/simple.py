"""Simple local reranker using keyword/semantic similarity - no API needed"""

import logging
import re
from collections import Counter
from typing import Any

from .base import RerankerProvider

logger = logging.getLogger(__name__)


class SimpleReranker(RerankerProvider):
    """
    Simple reranker that combines vector similarity with keyword matching.
    No external API required - runs locally.

    This helps with:
    - Boosting exact keyword matches
    - Penalizing duplicate/similar content
    - Basic relevance improvements without API costs
    """

    def __init__(self, keyword_weight: float = 0.3, dedupe_threshold: float = 0.85):
        """
        Initialize simple reranker.

        Args:
            keyword_weight: Weight for keyword matching (0-1), combined with vector score
            dedupe_threshold: Similarity threshold for deduplication (0-1)
        """
        self.keyword_weight = keyword_weight
        self.dedupe_threshold = dedupe_threshold
        logger.info("Initialized simple local reranker")

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization"""
        # Lowercase and split on non-alphanumeric
        words = re.findall(r'\b\w+\b', text.lower())
        # Filter short words and common stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
                     'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
                     'during', 'before', 'after', 'above', 'below', 'between',
                     'under', 'again', 'further', 'then', 'once', 'here', 'there',
                     'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
                     'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
                     'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and',
                     'but', 'if', 'or', 'because', 'until', 'while', 'this', 'that',
                     'these', 'those', 'what', 'which', 'who', 'whom', 'it', 'its'}
        return [w for w in words if len(w) > 2 and w not in stopwords]

    def _keyword_score(self, query: str, content: str) -> float:
        """Calculate keyword overlap score"""
        query_tokens = set(self._tokenize(query))
        content_tokens = self._tokenize(content)

        if not query_tokens or not content_tokens:
            return 0.0

        content_counter = Counter(content_tokens)

        # Score based on query term frequency in content
        matches = sum(content_counter.get(t, 0) for t in query_tokens)
        # Normalize by query length and content length
        score = matches / (len(query_tokens) * max(1, len(content_tokens) ** 0.5))

        return min(1.0, score * 10)  # Scale and cap at 1.0

    def _content_similarity(self, content1: str, content2: str) -> float:
        """Simple Jaccard similarity between two texts"""
        tokens1 = set(self._tokenize(content1))
        tokens2 = set(self._tokenize(content2))

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0

    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Rerank results using keyword matching and deduplication"""
        if not results:
            return results

        scored_results = []
        seen_contents = []

        for i, result in enumerate(results):
            content = result.get("text", "")
            vector_score = result.get("score", 0.5)

            # Check for near-duplicates
            is_duplicate = False
            for seen in seen_contents:
                if self._content_similarity(content, seen) > self.dedupe_threshold:
                    is_duplicate = True
                    break

            if is_duplicate:
                logger.debug(f"Skipping duplicate result {i}")
                continue

            seen_contents.append(content)

            # Calculate combined score
            keyword_score = self._keyword_score(query, content)
            combined_score = (
                (1 - self.keyword_weight) * vector_score +
                self.keyword_weight * keyword_score
            )

            scored_result = result.copy()
            scored_result["score"] = combined_score
            scored_result["_keyword_score"] = keyword_score
            scored_result["_vector_score"] = vector_score
            scored_results.append(scored_result)

        # Sort by combined score
        scored_results.sort(key=lambda x: x["score"], reverse=True)

        # Apply top_k limit
        if top_k:
            scored_results = scored_results[:top_k]

        logger.debug(f"Reranked {len(results)} results to {len(scored_results)} (deduped)")
        return scored_results

    def get_name(self) -> str:
        return "simple-local"
