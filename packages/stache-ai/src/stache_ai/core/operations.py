"""Shared operations for common RAG tasks"""

from stache_ai.rag.pipeline import get_pipeline
from stache_ai.providers import NamespaceProviderFactory
from stache_ai.config import settings
import uuid
import logging

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
        namespaces = provider.list()
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
