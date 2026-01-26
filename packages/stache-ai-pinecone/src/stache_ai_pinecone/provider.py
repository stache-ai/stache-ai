"""Pinecone vector database provider"""

from typing import List, Dict, Any, Optional
from stache_ai.providers.base import VectorDBProvider
from stache_ai.config import Settings
import uuid

try:
    from pinecone import Pinecone, ServerlessSpec
    PINECONE_AVAILABLE = True
except ImportError:
    PINECONE_AVAILABLE = False


class PineconeVectorDBProvider(VectorDBProvider):
    """Pinecone vector database provider"""

    def __init__(self, settings: Settings):
        if not PINECONE_AVAILABLE:
            raise ImportError("Pinecone package not installed. Run: pip install pinecone-client")

        self.settings = settings
        self.client = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index
        self.dimensions = settings.embedding_dimension
        self.default_namespace = settings.pinecone_namespace or "default"

        # Ensure index exists
        self._ensure_index()
        self.index = self.client.Index(self.index_name)

    def _ensure_index(self):
        """Create index if it doesn't exist"""
        existing_indexes = [index.name for index in self.client.list_indexes()]

        if self.index_name not in existing_indexes:
            self.client.create_index(
                name=self.index_name,
                dimension=self.dimensions,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud or "aws",
                    region=self.settings.pinecone_region or "us-east-1"
                )
            )

    def insert(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ) -> List[str]:
        """Insert vectors into Pinecone"""
        if not ids:
            ids = [str(uuid.uuid4()) for _ in vectors]

        if not metadatas:
            metadatas = [{} for _ in vectors]

        # Use provided namespace or default
        ns = namespace or self.default_namespace

        # Pinecone format: (id, vector, metadata)
        vectors_to_upsert = [
            (
                id_,
                vector,
                {**metadata, "text": text}
            )
            for id_, vector, text, metadata in zip(ids, vectors, texts, metadatas)
        ]

        self.index.upsert(vectors=vectors_to_upsert, namespace=ns)

        return ids

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors"""
        # Use provided namespace or default
        ns = namespace or self.default_namespace

        results = self.index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
            namespace=ns,
            filter=filter
        )

        return [
            {
                "id": match.id,
                "score": match.score,
                "content": match.metadata.get("text", ""),
                "metadata": {k: v for k, v in match.metadata.items() if k != "text"}
            }
            for match in results.matches
        ]

    def delete(self, ids: List[str], namespace: Optional[str] = None) -> bool:
        """Delete vectors by IDs"""
        # Use provided namespace or default
        ns = namespace or self.default_namespace
        self.index.delete(ids=ids, namespace=ns)
        return True

    def delete_by_metadata(self, field: str, value: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        """
        Delete vectors by metadata field value

        Args:
            field: Metadata field name (e.g., 'filename')
            value: Value to match
            namespace: Optional namespace filter

        Returns:
            Dictionary with deleted count and IDs
        """
        ns = namespace or self.default_namespace

        # Pinecone supports delete by filter
        self.index.delete(
            filter={field: {"$eq": value}},
            namespace=ns
        )

        # Pinecone doesn't return deleted IDs, so we return minimal info
        return {
            "deleted_count": -1,  # Unknown - Pinecone doesn't report this
            "deleted_ids": [],
            "filter": {field: value},
            "namespace": ns
        }

    def get_by_ids(
        self,
        ids: List[str],
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch vectors by IDs

        Args:
            ids: List of vector IDs
            namespace: Optional namespace filter

        Returns:
            List of dictionaries with id and metadata
        """
        ns = namespace or self.default_namespace

        # Pinecone fetch returns dict keyed by ID
        response = self.index.fetch(ids=ids, namespace=ns)

        results = []
        for vec_id, vec_data in response.vectors.items():
            metadata = vec_data.metadata or {}
            results.append({
                "id": vec_id,
                "metadata": metadata  # Keep text in metadata
            })

        return results

    def get_vectors_with_embeddings(
        self,
        ids: List[str],
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch vectors by IDs with their embeddings

        Args:
            ids: List of vector IDs
            namespace: Optional namespace filter

        Returns:
            List of dictionaries with id, vector, and metadata
        """
        if not ids:
            return []

        ns = namespace or self.default_namespace

        # Pinecone fetch returns dict keyed by ID
        response = self.index.fetch(ids=ids, namespace=ns)

        results = []
        for vec_id, vec_data in response.vectors.items():
            metadata = vec_data.metadata or {}
            results.append({
                "id": vec_id,
                "vector": vec_data.values,
                "metadata": metadata  # Include text here, don't extract it
            })

        return results

    @property
    def max_batch_size(self) -> int:
        """Maximum batch size for operations"""
        return 1000

    def get_collection_info(self) -> Dict[str, Any]:
        """Get index information"""
        stats = self.index.describe_index_stats()
        return {
            "name": self.index_name,
            "dimensions": self.dimensions,
            "total_vectors": stats.total_vector_count,
            "namespace": self.default_namespace
        }
