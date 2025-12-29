"""Health check endpoints"""

import logging

from fastapi import APIRouter

from stache_ai.config import settings
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping")
async def ping():
    """Lightweight connectivity check - no backend calls"""
    return {"ok": True}


@router.get("/health")
async def health_check():
    """Full health check - validates all provider connections"""
    try:
        # Try to initialize pipeline and providers
        pipeline = get_pipeline()
        provider_info = pipeline.get_providers_info()

        return {
            "status": "healthy",
            "providers": provider_info,
            "vectordb_provider": settings.vectordb_provider
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        # Don't expose detailed error messages to clients
        return {
            "status": "unhealthy",
            "error": "Service initialization failed"
        }
