"""Shared operations for common RAG tasks"""

import logging
import uuid

from stache_ai.config import settings
from stache_ai.providers import NamespaceProviderFactory
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)


def do_search(query: str, namespace: str = None, top_k: int = 20,
              rerank: bool = True, filter: dict = None, request_id: str = None) -> dict:
    """Search knowledge base - shared by HTTP routes and external integrations

    Args:
        query: Search query string
        namespace: Optional namespace to search within
        top_k: Number of results to return (max 50)
        rerank: Whether to rerank results for better relevance
        filter: Optional metadata filter (e.g., {"source": "meeting notes"})
        request_id: Optional request ID for tracking

    Returns:
        Dictionary with results and request_id
    """
    request_id = request_id or str(uuid.uuid4())

    # Enforce top_k max 50
    if top_k > 50:
        top_k = 50
        logger.warning(f"[{request_id}] top_k exceeded max of 50, clamping to 50")

    logger.info(f"[{request_id}] Search: query={query[:50]}..., namespace={namespace}, top_k={top_k}, rerank={rerank}, filter={filter}")

    try:
        pipeline = get_pipeline()
        result = pipeline.query(
            question=query,
            top_k=top_k,
            synthesize=False,  # ALWAYS disable synthesis
            namespace=namespace,
            rerank=rerank,
            filter=filter
        )
        return {"request_id": request_id, **result}
    except Exception as e:
        logger.error(f"[{request_id}] Search failed: {e}")
        return {
            "request_id": request_id,
            "error": str(e),
            "question": query,
            "sources": []
        }


def do_ingest_text(text: str, metadata: dict = None, namespace: str = None,
                   request_id: str = None) -> dict:
    """Ingest text - shared by HTTP routes and external integrations

    Args:
        text: Text to ingest
        metadata: Optional metadata dictionary
        namespace: Optional namespace for isolation
        request_id: Optional request ID for tracking

    Returns:
        Result dictionary with chunks_created and request_id

    Raises:
        ValueError: If text exceeds 100KB
    """
    request_id = request_id or str(uuid.uuid4())

    # Enforce max 100KB text
    text_bytes = text.encode('utf-8')
    if len(text_bytes) > 100 * 1024:  # 100KB
        error_msg = f"Text exceeds maximum size of 100KB (got {len(text_bytes) / 1024:.1f}KB)"
        logger.error(f"[{request_id}] {error_msg}")
        raise ValueError(error_msg)

    logger.info(f"[{request_id}] Ingest: {len(text)} chars, namespace={namespace}")

    try:
        pipeline = get_pipeline()
        result = pipeline.ingest_text(
            text=text,
            metadata=metadata,
            namespace=namespace
        )
        return {"request_id": request_id, **result}
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[{request_id}] Ingest failed: {e}")
        return {
            "request_id": request_id,
            "error": str(e),
            "success": False
        }


def do_list_namespaces(request_id: str = None) -> dict:
    """List namespaces - shared by HTTP routes and external integrations

    Args:
        request_id: Optional request ID for tracking

    Returns:
        Dictionary with namespaces list, count, and request_id
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] List namespaces")

    try:
        provider = NamespaceProviderFactory.create(settings)
        # include_children=True to get ALL namespaces, not just root level
        namespaces = provider.list(include_children=True)
        return {
            "request_id": request_id,
            "namespaces": namespaces,
            "count": len(namespaces)
        }
    except Exception as e:
        logger.error(f"[{request_id}] List namespaces failed: {e}")
        return {
            "request_id": request_id,
            "error": str(e),
            "namespaces": [],
            "count": 0
        }


def do_list_documents(namespace: str = None, limit: int = 50,
                      next_key: str = None, request_id: str = None) -> dict:
    """List documents - shared by HTTP routes and external integrations

    Args:
        namespace: Optional namespace to list from
        limit: Maximum documents to return (max 100)
        next_key: Optional pagination key
        request_id: Optional request ID for tracking

    Returns:
        Dictionary with documents list, next_key, and request_id
    """
    request_id = request_id or str(uuid.uuid4())

    # Enforce limit max 100
    if limit > 100:
        limit = 100
        logger.warning(f"[{request_id}] limit exceeded max of 100, clamping to 100")

    logger.info(f"[{request_id}] List documents: namespace={namespace}, limit={limit}")

    try:
        pipeline = get_pipeline()

        # Check if document index provider is available
        if pipeline.document_index_provider is None:
            logger.error(f"[{request_id}] Document index provider not available (feature flag disabled)")
            return {
                "request_id": request_id,
                "error": "Document index feature is disabled",
                "documents": [],
                "next_key": None
            }

        result = pipeline.document_index_provider.list_documents(
            namespace=namespace,
            limit=limit,
            last_evaluated_key=next_key
        )
        return {"request_id": request_id, **result}
    except Exception as e:
        logger.error(f"[{request_id}] List documents failed: {e}")
        return {
            "request_id": request_id,
            "error": str(e),
            "documents": [],
            "next_key": None
        }


def do_get_document(doc_id: str, namespace: str = "default",
                    request_id: str = None) -> dict:
    """Get document - shared by HTTP routes and external integrations

    Args:
        doc_id: Document ID to retrieve
        namespace: Namespace containing the document
        request_id: Optional request ID for tracking

    Returns:
        Document dictionary with request_id, or error dict
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] Get document: doc_id={doc_id}, namespace={namespace}")

    try:
        pipeline = get_pipeline()

        # Check if document index provider is available
        if pipeline.document_index_provider is None:
            logger.error(f"[{request_id}] Document index provider not available (feature flag disabled)")
            return {
                "request_id": request_id,
                "error": "Document index feature is disabled"
            }

        doc = pipeline.document_index_provider.get_document(
            doc_id=doc_id,
            namespace=namespace
        )

        if not doc:
            logger.info(f"[{request_id}] Document not found: {doc_id}")
            return {
                "request_id": request_id,
                "error": f"Document not found: {doc_id}"
            }

        return {"request_id": request_id, **doc}
    except Exception as e:
        logger.error(f"[{request_id}] Get document failed: {e}")
        return {
            "request_id": request_id,
            "error": str(e)
        }


# ===== Namespace Operations =====

def do_create_namespace(id: str, name: str, description: str = "",
                        parent_id: str = None, metadata: dict = None,
                        filter_keys: list = None, request_id: str = None) -> dict:
    """Create a namespace

    Args:
        id: Namespace ID (slug format, e.g., 'mba/finance')
        name: Display name
        description: What belongs in this namespace
        parent_id: Optional parent namespace ID
        metadata: Optional metadata dict
        filter_keys: Optional list of filterable metadata keys
        request_id: Optional request ID for tracking

    Returns:
        Created namespace dict with request_id
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] Create namespace: id={id}, name={name}")

    try:
        provider = NamespaceProviderFactory.create(settings)
        namespace = provider.create(
            id=id,
            name=name,
            description=description,
            parent_id=parent_id,
            metadata=metadata,
            filter_keys=filter_keys
        )
        return {"request_id": request_id, "namespace": namespace, "success": True}
    except Exception as e:
        logger.error(f"[{request_id}] Create namespace failed: {e}")
        return {"request_id": request_id, "error": str(e), "success": False}


def do_get_namespace(id: str, request_id: str = None) -> dict:
    """Get a namespace by ID

    Args:
        id: Namespace ID to retrieve
        request_id: Optional request ID for tracking

    Returns:
        Namespace dict with request_id, or error dict
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] Get namespace: id={id}")

    try:
        provider = NamespaceProviderFactory.create(settings)
        namespace = provider.get(id)

        if not namespace:
            return {"request_id": request_id, "error": f"Namespace not found: {id}"}

        return {"request_id": request_id, "namespace": namespace}
    except Exception as e:
        logger.error(f"[{request_id}] Get namespace failed: {e}")
        return {"request_id": request_id, "error": str(e)}


def do_update_namespace(id: str, name: str = None, description: str = None,
                        metadata: dict = None, request_id: str = None) -> dict:
    """Update a namespace

    Args:
        id: Namespace ID to update
        name: New display name (optional)
        description: New description (optional)
        metadata: Metadata to merge (optional)
        request_id: Optional request ID for tracking

    Returns:
        Updated namespace dict with request_id, or error dict
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] Update namespace: id={id}")

    try:
        provider = NamespaceProviderFactory.create(settings)
        namespace = provider.update(
            id=id,
            name=name,
            description=description,
            metadata=metadata
        )

        if not namespace:
            return {"request_id": request_id, "error": f"Namespace not found: {id}"}

        return {"request_id": request_id, "namespace": namespace, "success": True}
    except Exception as e:
        logger.error(f"[{request_id}] Update namespace failed: {e}")
        return {"request_id": request_id, "error": str(e), "success": False}


def do_delete_namespace(id: str, cascade: bool = False, request_id: str = None) -> dict:
    """Delete a namespace

    Args:
        id: Namespace ID to delete
        cascade: If True, delete children; if False, fail if children exist
        request_id: Optional request ID for tracking

    Returns:
        Success dict with request_id, or error dict
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] Delete namespace: id={id}, cascade={cascade}")

    try:
        provider = NamespaceProviderFactory.create(settings)
        deleted = provider.delete(id=id, cascade=cascade)

        if not deleted:
            return {"request_id": request_id, "error": f"Namespace not found: {id}", "success": False}

        return {"request_id": request_id, "success": True}
    except Exception as e:
        logger.error(f"[{request_id}] Delete namespace failed: {e}")
        return {"request_id": request_id, "error": str(e), "success": False}


# ===== Document Operations =====

def do_delete_document(doc_id: str, namespace: str = "default", request_id: str = None) -> dict:
    """Delete a document and all its chunks

    Args:
        doc_id: Document ID (UUID) to delete
        namespace: Namespace containing the document
        request_id: Optional request ID for tracking

    Returns:
        Success dict with chunks_deleted count, or error dict
    """
    request_id = request_id or str(uuid.uuid4())
    logger.info(f"[{request_id}] Delete document: doc_id={doc_id}, namespace={namespace}")

    try:
        pipeline = get_pipeline()

        # Use document index if available (preferred method)
        if pipeline.document_index_provider:
            # Get chunk IDs from document index
            chunk_ids = pipeline.document_index_provider.get_chunk_ids(doc_id, namespace)

            if not chunk_ids:
                return {
                    "request_id": request_id,
                    "error": f"Document not found: {doc_id}",
                    "success": False
                }

            # Delete from vector database first (atomic operation pattern)
            vectordb = pipeline.vectordb_provider
            vectordb.delete(chunk_ids, namespace=namespace)

            # Delete from document index
            pipeline.document_index_provider.delete_document(doc_id, namespace)

            logger.info(f"[{request_id}] Deleted document {doc_id} ({len(chunk_ids)} chunks) from {namespace}")

            return {
                "request_id": request_id,
                "success": True,
                "doc_id": doc_id,
                "namespace": namespace,
                "chunks_deleted": len(chunk_ids)
            }

        # Fallback: Use legacy vector DB deletion (for backwards compatibility)
        vectordb = pipeline.vectordb_provider
        result = vectordb.delete_by_metadata(
            field="doc_id",
            value=doc_id
        )

        # Also explicitly delete the summary record by its ID
        summary_id = f"summary_{doc_id}"
        try:
            vectordb.delete(ids=[summary_id])
        except Exception:
            pass  # Summary may not exist for older documents

        if result["deleted"] == 0:
            return {
                "request_id": request_id,
                "error": f"Document not found: {doc_id}",
                "success": False
            }

        logger.info(f"[{request_id}] Deleted {result['deleted']} chunks + summary for doc_id: {doc_id}")

        return {
            "request_id": request_id,
            "success": True,
            "doc_id": doc_id,
            "namespace": namespace,
            "chunks_deleted": result["deleted"]
        }
    except Exception as e:
        logger.error(f"[{request_id}] Delete document failed: {e}")
        return {"request_id": request_id, "error": str(e), "success": False}
