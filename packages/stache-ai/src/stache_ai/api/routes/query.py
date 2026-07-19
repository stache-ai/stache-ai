"""Query endpoint for searching knowledge base"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from stache_ai.api import auth
from stache_ai.identity import ForbiddenError, LimitExceededError
from stache_ai.middleware.context import RequestContext
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def _annotate_has_original(sources, pipeline, context) -> None:
    """Set ``has_original`` on each query source in place.

    True iff the source's document still has a retained original (its record
    carries a ``blob_key``) AND the active blob store can presign downloads.
    Sources carry only ``doc_id`` in chunk metadata, so the blob_key is resolved
    per distinct (namespace, doc_id) via one document-index lookup, cached. When
    the store advertises no presign support (the OSS default), no lookups run.
    """
    try:
        from stache_ai.ingestion.factory import get_ingestion_service
        capable = "presign_download" in get_ingestion_service().blobstore.capabilities
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception:
        capable = False

    cache: dict[tuple[str, str], bool] = {}
    for source in sources:
        metadata = source.get("metadata") or {}
        doc_id = metadata.get("doc_id")
        has_original = False
        if capable and doc_id:
            ns = metadata.get("namespace", "default")
            key = (ns, doc_id)
            if key not in cache:
                try:
                    record = pipeline.get_document_record(doc_id, ns, context=context)
                    cache[key] = bool(record and record.get("blob_key"))
                except ForbiddenError:
                    raise
                except LimitExceededError:
                    raise
                except Exception:
                    cache[key] = False
            has_original = cache[key]
        source["has_original"] = has_original


class QueryRequest(BaseModel):
    """Request model for query endpoint"""
    query: str
    top_k: int = 20
    synthesize: bool = True  # If False, return search results without LLM
    namespace: str | None = None
    rerank: bool = True  # Rerank results for better relevance and deduplication
    model: str | None = None  # Override default LLM model for synthesis
    filter: dict[str, Any] | None = None  # Metadata filter (e.g., {"source": "meeting notes"})


@router.post("/query")
async def query_knowledge(request: QueryRequest, http_request: Request):
    """
    Query your knowledge base with natural language

    - synthesize=True: Returns AI-synthesized answer from relevant chunks
    - synthesize=False: Returns raw search results (faster, no LLM cost)
    - namespace: Optional namespace to search within
    - model: Optional model ID to use for synthesis (e.g., us.anthropic.claude-3-5-sonnet-20241022-v2:0)
    - filter: Optional metadata filter (e.g., {"source": "meeting notes"})
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    # "query" deliberately unifies /query and /insights/search: both are
    # same-scope semantic reads, so they share one read op rather than each
    # carrying its own verb.
    auth.authorize(http_request, "query",
                   {"namespace": request.namespace} if request.namespace else None)

    try:
        pipeline = get_pipeline()

        context = RequestContext.from_fastapi_request(
            http_request, request.namespace or "")
        result = await pipeline.query(
            question=request.query,
            top_k=request.top_k,
            synthesize=request.synthesize,
            namespace=request.namespace,
            rerank=request.rerank,
            model=request.model,
            filter=request.filter,
            context=context,
        )

        _annotate_has_original(result.get("sources", []), pipeline, context)

        return result
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
