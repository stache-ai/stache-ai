"""Namespace management endpoints"""

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator

from stache_ai.config import settings
from stache_ai.providers import NamespaceProviderFactory
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton namespace provider instance
_namespace_provider = None


def get_namespace_provider():
    """Get or create namespace provider singleton"""
    global _namespace_provider
    if _namespace_provider is None:
        _namespace_provider = NamespaceProviderFactory.create(settings)
    return _namespace_provider


# ===== Request Models =====

class NamespaceCreate(BaseModel):
    """Request model for creating a namespace"""
    id: str = Field(..., description="Unique namespace ID (slug format, e.g., 'mba/finance')")
    name: str = Field(..., description="Display name (e.g., 'Finance')")
    description: str = Field("", description="Description of what belongs in this namespace")
    parent_id: str | None = Field(None, description="Parent namespace ID for hierarchy")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata (tags, icon, color)")
    filter_keys: list[str] | None = Field(
        None,
        description="Valid metadata keys for filtering searches (e.g., ['source', 'date', 'author'])",
        max_length=50
    )

    @field_validator('filter_keys')
    @classmethod
    def validate_filter_keys(cls, v):
        """Validate and deduplicate filter keys"""
        if v is None:
            return v

        # Remove duplicates while preserving order
        seen = set()
        result = []
        for key in v:
            if not key or not isinstance(key, str):
                raise ValueError("Filter keys must be non-empty strings")
            # Allow alphanumeric, underscores, hyphens
            if not key.replace('_', '').replace('-', '').isalnum():
                raise ValueError(f"Invalid filter key format: '{key}'. Use alphanumeric, underscore, or hyphen only.")
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result


class NamespaceUpdate(BaseModel):
    """Request model for updating a namespace"""
    name: str | None = Field(None, description="New display name")
    description: str | None = Field(None, description="New description")
    parent_id: str | None = Field(None, description="New parent ID (empty string to make root)")
    metadata: dict[str, Any] | None = Field(None, description="Metadata to merge")
    filter_keys: list[str] | None = Field(
        None,
        description="New list of valid filter keys (replaces existing entirely)",
        max_length=50
    )

    @field_validator('filter_keys')
    @classmethod
    def validate_filter_keys(cls, v):
        """Validate and deduplicate filter keys"""
        if v is None:
            return v

        seen = set()
        result = []
        for key in v:
            if not key or not isinstance(key, str):
                raise ValueError("Filter keys must be non-empty strings")
            if not key.replace('_', '').replace('-', '').isalnum():
                raise ValueError(f"Invalid filter key format: '{key}'. Use alphanumeric, underscore, or hyphen only.")
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result


# ===== Helper Functions =====

def get_namespace_stats(namespace_id: str) -> dict[str, int]:
    """Get document and chunk counts for a namespace

    Uses the document index provider (DynamoDB) for efficient counting
    instead of scanning the vector database.
    """
    try:
        pipeline = get_pipeline()
        doc_index = pipeline.document_index_provider

        if doc_index:
            return doc_index.count_by_namespace(namespace_id)

        # Fallback to zeros if no document index provider
        return {"doc_count": 0, "chunk_count": 0}
    except Exception as e:
        logger.warning(f"Could not get stats for namespace {namespace_id}: {e}")
        return {"doc_count": 0, "chunk_count": 0}


def enrich_namespace_with_stats(namespace: dict[str, Any]) -> dict[str, Any]:
    """Add document and chunk counts to namespace"""
    namespace_id = namespace["id"]
    stats = get_namespace_stats(namespace_id)
    return {
        **namespace,
        "doc_count": stats["doc_count"],
        "chunk_count": stats["chunk_count"]
    }


# ===== Endpoints =====

@router.post("/namespaces")
async def create_namespace(data: NamespaceCreate):
    """
    Create a new namespace.

    Namespaces organize your knowledge base into logical sections.
    Use hierarchical IDs like 'mba/finance/corporate-finance' for nested organization.
    """
    try:
        provider = get_namespace_provider()
        namespace = provider.create(
            id=data.id,
            name=data.name,
            description=data.description,
            parent_id=data.parent_id,
            metadata=data.metadata,
            filter_keys=data.filter_keys
        )
        logger.info(f"Created namespace: {data.id}")
        return enrich_namespace_with_stats(namespace)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create namespace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/namespaces")
async def list_namespaces(
    parent_id: str | None = Query(None, description="Filter by parent namespace"),
    include_children: bool = Query(False, description="Include all descendants (flat list)"),
    include_stats: bool = Query(True, description="Include document/chunk counts (slower)")
):
    """
    List all namespaces.

    - Without filters: Returns root namespaces only
    - With parent_id: Returns direct children of that namespace
    - With include_children=true: Returns all namespaces as a flat list
    - With include_stats=true (default): Adds doc_count and chunk_count
    """
    try:
        provider = get_namespace_provider()
        namespaces = provider.list(parent_id=parent_id, include_children=include_children)

        if include_stats:
            namespaces = [enrich_namespace_with_stats(ns) for ns in namespaces]

        return {
            "namespaces": namespaces,
            "count": len(namespaces)
        }
    except Exception as e:
        logger.error(f"Failed to list namespaces: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/namespaces/tree")
async def get_namespace_tree(
    root_id: str | None = Query(None, description="Get subtree starting from this namespace"),
    include_stats: bool = Query(False, description="Include document/chunk counts (slower)")
):
    """
    Get namespaces as a hierarchical tree.

    Returns nested structure with 'children' arrays for navigation UI.
    """
    try:
        provider = get_namespace_provider()
        tree = provider.get_tree(root_id=root_id)

        if include_stats:
            # Recursively add stats to tree
            def add_stats_recursive(nodes: list[dict]) -> list[dict]:
                for node in nodes:
                    stats = get_namespace_stats(node["id"])
                    node["doc_count"] = stats["doc_count"]
                    node["chunk_count"] = stats["chunk_count"]
                    if node.get("children"):
                        add_stats_recursive(node["children"])
                return nodes
            tree = add_stats_recursive(tree)

        return {
            "tree": tree,
            "count": len(tree)
        }
    except Exception as e:
        logger.error(f"Failed to get namespace tree: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/namespaces/{namespace_id:path}")
async def get_namespace(
    namespace_id: str = Path(..., description="Namespace ID")
):
    """
    Get a single namespace by ID with full stats.

    Also returns the namespace path (breadcrumb) and ancestors.
    """
    try:
        provider = get_namespace_provider()
        namespace = provider.get(namespace_id)

        if not namespace:
            raise HTTPException(status_code=404, detail=f"Namespace not found: {namespace_id}")

        # Enrich with stats and path info
        result = enrich_namespace_with_stats(namespace)
        result["path"] = provider.get_path(namespace_id)
        result["ancestors"] = provider.get_ancestors(namespace_id)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get namespace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/namespaces/{namespace_id:path}")
async def update_namespace(
    namespace_id: str = Path(..., description="Namespace ID"),
    data: NamespaceUpdate = Body(...)
):
    """
    Update a namespace.

    Only provided fields will be updated. Metadata is merged with existing.
    """
    try:
        provider = get_namespace_provider()

        # Handle empty string parent_id as None (make it a root)
        parent_id = data.parent_id
        if parent_id == "":
            parent_id = None

        namespace = provider.update(
            id=namespace_id,
            name=data.name,
            description=data.description,
            parent_id=parent_id,
            metadata=data.metadata,
            filter_keys=data.filter_keys
        )

        if not namespace:
            raise HTTPException(status_code=404, detail=f"Namespace not found: {namespace_id}")

        logger.info(f"Updated namespace: {namespace_id}")
        return enrich_namespace_with_stats(namespace)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update namespace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/namespaces/{namespace_id:path}")
async def delete_namespace(
    namespace_id: str = Path(..., description="Namespace ID"),
    cascade: bool = Query(False, description="Delete child namespaces too"),
    delete_documents: bool = Query(True, description="Also delete all documents in namespace from vector DB")
):
    """
    Delete a namespace.

    - cascade=true: Also delete all child namespaces
    - delete_documents=true (default): Also delete all documents from vector DB
    - delete_documents=false: Keep documents but delete namespace metadata only

    By default, fails if namespace has children (use cascade=true to force).
    """
    try:
        provider = get_namespace_provider()

        # Check if namespace exists
        namespace = provider.get(namespace_id)
        if not namespace:
            raise HTTPException(status_code=404, detail=f"Namespace not found: {namespace_id}")

        # Optionally delete documents from vector DB
        total_deleted = 0
        if delete_documents:
            pipeline = get_pipeline()

            # Delete from documents provider (primary)
            try:
                result = pipeline.documents_provider.delete_by_metadata(
                    field="namespace",
                    value=namespace_id
                )
                total_deleted += result.get('deleted', 0)
                logger.info(f"Deleted {result['deleted']} chunks from documents provider for namespace: {namespace_id}")
            except Exception as e:
                logger.error(f"Failed to delete from documents provider for namespace {namespace_id}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to delete documents: {e}. Namespace not deleted."
                )

            # Delete from summaries provider (secondary)
            try:
                result = pipeline.summaries_provider.delete_by_metadata(
                    field="namespace",
                    value=namespace_id
                )
                total_deleted += result.get('deleted', 0)
                logger.info(f"Deleted {result['deleted']} summaries from summaries provider for namespace: {namespace_id}")
            except Exception as e:
                logger.error(f"Failed to delete from summaries provider for namespace {namespace_id}: {e}")
                # Don't fail - summaries are secondary

        # Delete namespace from registry
        success = provider.delete(namespace_id, cascade=cascade)

        if not success:
            raise HTTPException(status_code=404, detail=f"Namespace not found: {namespace_id}")

        logger.info(f"Deleted namespace: {namespace_id}")
        return {
            "success": True,
            "namespace_id": namespace_id,
            "cascade": cascade,
            "documents_deleted": delete_documents,
            "chunks_deleted": total_deleted
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete namespace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/namespaces/{namespace_id:path}/documents")
async def list_namespace_documents(
    namespace_id: str = Path(..., description="Namespace ID"),
    limit: int = Query(100, description="Max documents to return"),
    offset: int = Query(0, description="Pagination offset")
):
    """
    List all documents in a namespace.

    Returns documents with their metadata from the vector DB.
    Uses the provider-agnostic list_by_filter method.
    """
    try:
        # Verify namespace exists
        provider = get_namespace_provider()
        namespace = provider.get(namespace_id)
        if not namespace:
            raise HTTPException(status_code=404, detail=f"Namespace not found: {namespace_id}")

        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider

        # Use provider-agnostic list method
        vectors = vectordb.list_by_filter(
            filter={"namespace": namespace_id},
            fields=["doc_id", "filename", "total_chunks", "created_at"],
            limit=10000  # Upper bound for unique doc extraction
        )

        # Collect unique documents
        docs = {}
        for vector in vectors:
            doc_id = vector.get("doc_id")
            if doc_id and doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "filename": vector.get("filename"),
                    "total_chunks": vector.get("total_chunks"),
                    "created_at": vector.get("created_at")
                }

        # Sort by created_at and paginate
        documents = sorted(
            docs.values(),
            key=lambda x: x.get("created_at") or "",
            reverse=True
        )

        total = len(documents)
        documents = documents[offset:offset + limit]

        return {
            "namespace": namespace_id,
            "documents": documents,
            "count": len(documents),
            "total": total,
            "offset": offset,
            "limit": limit
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list namespace documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))
