"""FastAPI application entry point"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from stache_ai.api.routes import (
    capture,
    documents,
    health,
    insights,
    models,
    namespaces,
    pending,
    query,
    upload,
)
from stache_ai.config import settings

# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Stache AI API",
    description="AI-powered knowledge base and RAG system",
    version="0.1.0"
)

# CORS middleware - configure via environment for production
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])  # /health for local dev
app.include_router(health.router, prefix="/api", tags=["health"])  # /api/health for Lambda
app.include_router(capture.router, prefix="/api", tags=["capture"])
app.include_router(query.router, prefix="/api", tags=["query"])
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
app.include_router(pending.router, prefix="/api", tags=["pending"])
app.include_router(namespaces.router, prefix="/api", tags=["namespaces"])
app.include_router(models.router, prefix="/api", tags=["models"])
app.include_router(insights.router, prefix="/api", tags=["insights"])

# Serve static frontend files
static_dir = Path("/app/static")
if static_dir.exists():
    # Mount static assets (JS, CSS, etc.)
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    # Catch-all route for SPA - must be last
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the frontend SPA for all non-API routes"""
        # Don't interfere with API routes
        if full_path.startswith("api/") or full_path == "health":
            return {"error": "Not found"}, 404

        # Serve index.html for SPA routing
        return FileResponse(str(static_dir / "index.html"))


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting Stache AI API...")
    logger.info(f"LLM Provider: {settings.llm_provider}")
    logger.info(f"Embedding Provider: {settings.embedding_provider}")
    logger.info(f"Vector DB: {settings.qdrant_url}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Stache AI API...")
