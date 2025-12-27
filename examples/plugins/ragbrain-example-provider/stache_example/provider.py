"""Example vector database provider

This is a minimal implementation showing the required interface.
In production, implement actual storage logic.
"""

from typing import List, Dict, Any, Optional, Set
from stache.providers.base import VectorDBProvider
from stache.config import Settings


class ExampleVectorDBProvider(VectorDBProvider):
    """Example provider - stores vectors in memory

    This is for demonstration only. Real providers should
    persist data to external storage.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.vectors = {}  # In-memory storage (not for production!)

    @property
    def capabilities(self) -> Set[str]:
        return {"vector_search", "metadata_filter"}

    def insert(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ) -> List[str]:
        """Insert vectors (minimal implementation)"""
        import uuid
        ids = ids or [str(uuid.uuid4()) for _ in vectors]

        for i, vid in enumerate(ids):
            self.vectors[vid] = {
                "vector": vectors[i],
                "text": texts[i],
                "metadata": metadatas[i] if metadatas else {},
                "namespace": namespace
            }

        return ids

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search vectors (minimal implementation)"""
        # Simple example - real implementation would use
        # proper similarity search algorithms
        results = []
        for vid, data in self.vectors.items():
            if namespace and data["namespace"] != namespace:
                continue
            results.append({
                "id": vid,
                "text": data["text"],
                "metadata": data["metadata"],
                "score": 0.5  # Placeholder
            })
        return results[:top_k]

    def delete(
        self,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> int:
        """Delete vectors"""
        if ids:
            deleted = 0
            for vid in ids:
                if vid in self.vectors:
                    del self.vectors[vid]
                    deleted += 1
            return deleted
        return 0

    def count(self, namespace: Optional[str] = None) -> int:
        """Count vectors"""
        if namespace:
            return sum(1 for v in self.vectors.values() if v["namespace"] == namespace)
        return len(self.vectors)
