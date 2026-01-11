"""Document summary generation via PostIngestProcessor middleware.

This module extracts the heuristic summary generation logic from the
pipeline into a reusable middleware component.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import RequestContext
    from ..base import StorageResult
    from ..results import PostIngestResult

from ..base import PostIngestProcessor
from ..results import PostIngestResult

logger = logging.getLogger(__name__)


class HeuristicSummaryGenerator(PostIngestProcessor):
    """Generate document summaries for semantic discovery.

    Creates a summary record in the vector DB with:
    - Document info (filename, namespace, doc_id)
    - Headings extracted from chunks (for semantic search)
    - First ~1500 chars of content (for topic matching)
    - Chunk count for display

    The summary record has _type: "document_summary" to distinguish
    it from regular chunks.

    This is a direct extraction of the original pipeline._create_document_summary
    logic, converted to the middleware pattern.
    """

    priority = 50  # Run early (lower priority value = earlier execution)

    async def process(
        self,
        chunks: list[tuple[str, dict[str, Any]]],
        storage_result: StorageResult,
        context: "RequestContext"
    ) -> "PostIngestResult":
        """Generate document summary from stored chunks.

        Args:
            chunks: List of (text, metadata) tuples that were stored
            storage_result: Details about the storage operation (doc_id, namespace, etc.)
            context: Request context with provider access

        Returns:
            PostIngestResult with artifacts:
            - "summary": str (the summary text)
            - "summary_embedding": list[float] (embedding vector)
            - "headings": list[str] (extracted headings)
            - "summary_id": str (UUID for the summary record)
        """
        # Access configuration from context
        config = context.custom.get("config")
        if not config:
            return PostIngestResult(
                action="skip",
                reason="Config not available in context"
            )
        if not config.enable_summary_generation:
            return PostIngestResult(
                action="skip",
                reason="Summary generation disabled via config"
            )

        # Access providers from context
        embedding_provider = context.custom.get("embedding_provider")
        summaries_provider = context.custom.get("summaries_provider")

        if not embedding_provider or not summaries_provider:
            return PostIngestResult(
                action="skip",
                reason="Required providers not available in context"
            )

        try:
            # Get document metadata from storage_result
            doc_id = storage_result.doc_id
            namespace = storage_result.namespace

            # Extract filename and created_at from chunk metadata
            # (These should be consistent across all chunks from the same document)
            filename = "unknown"
            created_at = ""
            original_metadata = {}

            if chunks:
                first_chunk_meta = chunks[0][1]
                filename = first_chunk_meta.get("filename", "unknown")
                created_at = first_chunk_meta.get("created_at", "")
                # Copy original document metadata (excluding chunk-specific fields)
                original_metadata = {
                    k: v for k, v in first_chunk_meta.items()
                    if k not in ("text", "chunk_index", "headings", "_type", "doc_id")
                }

            # Extract unique headings from chunk metadata (from hierarchical chunking)
            headings = []
            seen_headings = set()
            for chunk_text, chunk_meta in chunks:
                for heading in chunk_meta.get("headings", []):
                    if heading and heading not in seen_headings:
                        headings.append(heading)
                        seen_headings.add(heading)

            # Build summary text for semantic search
            # Format: Document: {filename}\nNamespace: {namespace}\nHeadings: {...}\n\n{first 500 chars}
            summary_parts = [
                f"Document: {filename}",
                f"Namespace: {namespace}"
            ]

            if headings:
                summary_parts.append(f"Headings: {', '.join(headings[:20])}")  # Limit to 20 headings

            # Add first ~1500 chars of content from first chunks for better semantic matching
            content_preview = ""
            char_count = 0
            for chunk_text, _ in chunks:
                remaining = 1500 - char_count
                if remaining <= 0:
                    break
                content_preview += chunk_text[:remaining] + " "
                char_count += len(chunk_text[:remaining])

            if content_preview.strip():
                summary_parts.append("")  # Empty line before content
                summary_parts.append(content_preview.strip())

            summary_text = "\n".join(summary_parts)

            # Generate embedding for summary (wrapped in asyncio.to_thread for async)
            summary_embedding_list = await asyncio.to_thread(
                embedding_provider.embed, [summary_text]
            )
            summary_embedding = summary_embedding_list[0]

            # Create summary record - use a new UUID
            summary_id = str(uuid.uuid4())
            summary_metadata = {
                "_type": "document_summary",
                "doc_id": doc_id,
                "filename": filename,
                "namespace": namespace,
                "chunk_count": len(chunks),
                "created_at": created_at,
                **original_metadata
            }
            # Only include headings if non-empty (S3 Vectors rejects empty arrays)
            if headings:
                summary_metadata["headings"] = headings[:50]

            # Insert summary record into summaries provider
            summaries_provider.insert(
                vectors=[summary_embedding],
                texts=[summary_text],
                metadatas=[summary_metadata],
                ids=[summary_id],
                namespace=namespace
            )

            logger.info(f"Created document summary for {filename} (doc_id: {doc_id}, headings: {len(headings)})")

            # Return artifacts for document index creation
            return PostIngestResult(
                action="allow",
                artifacts={
                    "summary": summary_text,
                    "summary_embedding": summary_embedding,
                    "headings": headings,
                    "summary_id": summary_id
                }
            )

        except Exception as e:
            # Don't fail ingestion - just log and skip
            logger.error(f"Failed to create document summary: {e}")
            return PostIngestResult(
                action="skip",
                reason=f"Summary generation failed: {str(e)}"
            )
