#!/usr/bin/env python3
"""Stache MCP Server - Local stdio proxy to REST API.

This server exposes Stache tools to Claude Code via stdio transport.
Supports both local (no auth) and cloud (Cognito auth) modes.

Usage:
    # Local mode (no auth required)
    export STACHE_API_URL="http://localhost:8000"
    python stache_mcp.py

    # Cloud mode (Cognito auth)
    export STACHE_API_URL="https://your-api-gateway-url.amazonaws.com"
    export COGNITO_CLIENT_ID="your-client-id"
    export COGNITO_CLIENT_SECRET="your-client-secret"
    export COGNITO_TOKEN_URL="https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token"
    python stache_mcp.py
"""

import os
import time
import logging
import httpx
from typing import Optional
from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (stdout is for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("stache-mcp")

# Configuration from environment
# For local development: export STACHE_API_URL="http://localhost:8000"
# For cloud: provide all environment variables (no defaults to prevent accidents)
API_URL = os.environ.get("STACHE_API_URL")
if not API_URL:
    raise ValueError(
        "STACHE_API_URL environment variable is required.\n"
        "For local development, set: export STACHE_API_URL='http://localhost:8000'\n"
        "For cloud deployment, set to your API Gateway URL."
    )

COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET", "")
COGNITO_TOKEN_URL = os.environ.get("COGNITO_TOKEN_URL", "")

# Token cache
_token_cache = {
    "access_token": None,
    "expires_at": 0
}


def get_access_token() -> Optional[str]:
    """Get a valid access token, refreshing if needed. Returns None if no credentials configured."""
    # Skip auth if no credentials configured (local mode)
    if not COGNITO_CLIENT_ID or not COGNITO_CLIENT_SECRET:
        return None

    now = time.time()

    # Return cached token if still valid (with 60s buffer)
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    # Get new token via client credentials flow
    logger.info("Refreshing Cognito access token...")

    response = httpx.post(
        COGNITO_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": COGNITO_CLIENT_ID,
            "client_secret": COGNITO_CLIENT_SECRET,
            "scope": "stache-mcp/read stache-mcp/write"
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    response.raise_for_status()

    token_data = response.json()
    _token_cache["access_token"] = token_data["access_token"]
    _token_cache["expires_at"] = now + token_data.get("expires_in", 3600)

    logger.info("Token refreshed successfully")
    return _token_cache["access_token"]


def api_request(method: str, path: str, **kwargs) -> dict:
    """Make request to Stache API (with auth if credentials configured)."""
    token = get_access_token()

    url = f"{API_URL.rstrip('/')}/api{path}"
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.request(method, url, headers=headers, timeout=30.0, **kwargs)
    response.raise_for_status()

    return response.json()


# Create MCP server
mcp = FastMCP("ragbrain")


@mcp.tool()
def search(
    query: str,
    namespace: Optional[str] = None,
    top_k: int = 20,
    rerank: bool = True,
    filter: Optional[dict] = None
) -> dict:
    """Search the RAGBrain knowledge base.

    Args:
        query: Natural language search query
        namespace: Optional namespace to search within (e.g., 'mba/finance')
        top_k: Maximum number of results to return (default 20, max 50)
        rerank: Whether to rerank results for better relevance (default True)
        filter: Optional metadata filter (e.g., {"source": "meeting notes", "date": "2025-01-15"})

    Returns:
        Search results with relevant document chunks and their sources
    """
    top_k = min(top_k, 50)  # Enforce max

    request_body = {
        "query": query,
        "namespace": namespace,
        "top_k": top_k,
        "rerank": rerank,
        "synthesize": False  # Claude does its own synthesis
    }
    if filter:
        request_body["filter"] = filter

    return api_request("POST", "/query", json=request_body)


@mcp.tool()
def list_namespaces() -> dict:
    """List all available namespaces in the knowledge base.

    Returns:
        List of namespaces with their names, descriptions, document counts,
        and filter_keys (valid metadata keys for filtering searches)
    """
    return api_request("GET", "/namespaces", params={
        "include_children": True,
        "include_stats": True
    })


@mcp.tool()
def list_documents(
    namespace: Optional[str] = None,
    limit: int = 50,
    next_key: Optional[str] = None
) -> dict:
    """List documents in the knowledge base.

    Args:
        namespace: Optional namespace to filter by
        limit: Maximum documents to return (default 50, max 100)
        next_key: Pagination token from previous response

    Returns:
        List of documents with metadata and pagination token
    """
    limit = min(limit, 100)  # Enforce max

    params = {"limit": limit}
    if namespace:
        params["namespace"] = namespace
    if next_key:
        params["next_key"] = next_key

    return api_request("GET", "/documents", params=params)


@mcp.tool()
def get_document(
    doc_id: str,
    namespace: str = "default"
) -> dict:
    """Get detailed information about a specific document.

    Args:
        doc_id: The document's UUID
        namespace: The namespace containing the document (default 'default')

    Returns:
        Document metadata including filename, summary, headings, and chunk count
    """
    return api_request("GET", f"/documents/id/{doc_id}", params={
        "namespace": namespace
    })


@mcp.tool()
def ingest_text(
    text: str,
    namespace: Optional[str] = None,
    metadata: Optional[dict] = None
) -> dict:
    """Ingest text content into the knowledge base.

    Args:
        text: The text content to ingest (max 100KB)
        namespace: Target namespace (default 'default')
        metadata: Optional metadata dict (e.g., {"source": "meeting notes", "date": "2025-01-15"})

    Returns:
        Ingestion result with doc_id and chunk count
    """
    # Enforce max text size (100KB)
    if len(text) > 100 * 1024:
        return {"error": "Text exceeds maximum size of 100KB"}

    return api_request("POST", "/capture", json={
        "text": text,
        "namespace": namespace,
        "metadata": metadata
    })


if __name__ == "__main__":
    # Log mode
    if COGNITO_CLIENT_ID and COGNITO_CLIENT_SECRET:
        logger.info(f"Starting RAGBrain MCP server (API: {API_URL}, auth: Cognito)")
    else:
        logger.info(f"Starting RAGBrain MCP server (API: {API_URL}, auth: none)")

    mcp.run()
