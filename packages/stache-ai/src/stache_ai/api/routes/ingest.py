"""Unified ingestion endpoints: POST /ingest, GET /jobs, GET /jobs/{id}.

The portable submit -> poll contract. In the synchronous tier the worker runs
inline, so POST /ingest returns a job that is already terminal (200 with
status done/skipped + doc_id). Async tiers (Phase 2) return 202 + queued.
"""

import base64
import binascii
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from stache_ai.api import auth
from stache_ai.config import settings
from stache_ai.ingestion import TERMINAL, JobStatus
from stache_ai.ingestion.factory import get_ingestion_service
from stache_ai.sanitize import strip_reserved_metadata

logger = logging.getLogger(__name__)

router = APIRouter()


class IngestRequest(BaseModel):
    """POST /ingest body.

    Provide exactly one of `text` (inline note) or `data_base64` (small file
    bytes). `content_type` is "text"/"markdown" for text, or a file MIME/type
    hint otherwise.
    """

    namespace: str | None = None
    filename: str | None = None
    content_type: str = "text"
    metadata: dict | None = None
    text: str | None = None
    data_base64: str | None = None
    chunking_strategy: str = "recursive"
    wait: bool = False
    upload: bool = False


def _status_code(status: JobStatus) -> int:
    return 200 if status in TERMINAL else 202


@router.post("/ingest")
async def ingest(request: IngestRequest, http_request: Request):
    principal = auth.principal(http_request)
    namespace = request.namespace or settings.default_namespace
    auth.assert_can_write(principal, namespace)   # S1 hook (no-op in Phase 1)

    service = get_ingestion_service()

    # Presigned-upload flow: no bytes in the request, return an upload URL.
    if request.upload:
        if not request.filename:
            raise HTTPException(status_code=400, detail="'filename' is required for upload")
        try:
            job, ticket = await service.begin_upload(
                namespace=namespace,
                content_type=request.content_type,
                requested_by=principal,
                filename=request.filename,
                source="api",
                metadata=strip_reserved_metadata(request.metadata),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return JSONResponse(
            status_code=200,
            content={
                **job.to_dict(),
                "upload_url": ticket.upload_url,
                "required_headers": ticket.required_headers,
            },
        )

    if request.text is None and request.data_base64 is None:
        raise HTTPException(status_code=400, detail="Provide either 'text' or 'data_base64'")
    if request.text is not None and request.data_base64 is not None:
        raise HTTPException(status_code=400, detail="Provide only one of 'text' or 'data_base64'")

    data = None
    if request.data_base64 is not None:
        try:
            data = base64.b64decode(request.data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="Invalid base64 in 'data_base64'")

    job = await service.submit(
        namespace=namespace,
        content_type=request.content_type,
        requested_by=principal,
        filename=request.filename,
        source="api",
        metadata=strip_reserved_metadata(request.metadata),
        text=request.text,
        data=data,
        chunking_strategy=request.chunking_strategy,
        wait=request.wait,
        wait_timeout=settings.ingest_wait_default_timeout,
        poll_interval=settings.ingest_wait_poll_interval,
    )
    return JSONResponse(status_code=_status_code(job.status), content=job.to_dict())


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, http_request: Request):
    principal = auth.principal(http_request)
    service = get_ingestion_service()
    job = service.get_job(job_id)
    # Scope to the requester; 404 (not 403) on mismatch so we don't leak existence.
    if job is None or job.requested_by != principal.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/jobs")
async def list_jobs(
    http_request: Request,
    status: str | None = None,
    limit: int = 50,
):
    principal = auth.principal(http_request)
    status_filter = None
    if status is not None:
        try:
            status_filter = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    service = get_ingestion_service()
    jobs, cursor = service.list_jobs(
        requested_by=principal.user_id, status=status_filter, limit=limit,
        principal=principal,
    )
    return {"jobs": [j.to_dict() for j in jobs], "cursor": cursor, "count": len(jobs)}
