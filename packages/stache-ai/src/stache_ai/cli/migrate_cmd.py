"""Migration command for creating document summaries for existing documents."""

import logging
from collections import defaultdict
from datetime import datetime, timezone

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option('--namespace', '-n', default=None, help='Only migrate documents in this namespace')
@click.option('--dry-run', is_flag=True, help='Show what would be migrated without making changes')
@click.option('--batch-size', default=1000, help='Number of points to scroll at a time')
def migrate_summaries(namespace: str | None, dry_run: bool, batch_size: int):
    """
    Create document summary records for existing documents.

    This migration scans all chunks, groups them by doc_id, and creates
    summary records for documents that don't already have one.

    The summary records enable fast document listing and semantic discovery.
    """
    console.print("[bold]Document Summary Migration[/bold]")
    console.print()

    pipeline = get_pipeline()
    vectordb = pipeline.vectordb_provider

    # Provider check
    if "metadata_scan" not in vectordb.capabilities:
        console.print("[yellow]This migration is only needed for Qdrant deployments.[/yellow]")
        console.print("S3 Vectors users: summaries are created automatically during ingestion.")
        console.print("No migration needed.")
        return

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    # First, collect all existing summary doc_ids
    console.print("Checking for existing summaries...")
    existing_summaries = set()
    offset = None

    while True:
        points, offset = vectordb.client.scroll(
            collection_name=vectordb.collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="_type", match=MatchValue(value="document_summary"))]
            ),
            limit=batch_size,
            offset=offset,
            with_payload=["doc_id"],
            with_vectors=False
        )

        for point in points:
            doc_id = point.payload.get("doc_id")
            if doc_id:
                existing_summaries.add(doc_id)

        if offset is None:
            break

    console.print(f"Found {len(existing_summaries)} existing summaries")

    # Now scan all chunks and group by doc_id
    console.print("Scanning documents...")
    documents = defaultdict(lambda: {
        "chunks": [],
        "filename": None,
        "namespace": None,
        "created_at": None,
        "headings": []
    })

    # Build scroll filter
    scroll_filter = None
    if namespace:
        scroll_filter = Filter(
            must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
        )

    offset = None
    total_chunks = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("Scanning chunks...", total=None)

        while True:
            points, offset = vectordb.client.scroll(
                collection_name=vectordb.collection_name,
                scroll_filter=scroll_filter,
                limit=batch_size,
                offset=offset,
                with_payload=["doc_id", "filename", "namespace", "text", "created_at", "headings", "_type"],
                with_vectors=False
            )

            for point in points:
                # Skip summary records
                if point.payload.get("_type") == "document_summary":
                    continue

                doc_id = point.payload.get("doc_id")
                if not doc_id:
                    continue  # Skip orphaned chunks

                # Skip if already has summary
                if doc_id in existing_summaries:
                    continue

                doc = documents[doc_id]
                doc["chunks"].append(point.payload.get("text", ""))
                doc["filename"] = doc["filename"] or point.payload.get("filename")
                doc["namespace"] = doc["namespace"] or point.payload.get("namespace", "default")
                doc["created_at"] = doc["created_at"] or point.payload.get("created_at")

                # Collect headings from chunks
                chunk_headings = point.payload.get("headings", [])
                if chunk_headings:
                    for h in chunk_headings:
                        if h and h not in doc["headings"]:
                            doc["headings"].append(h)

                total_chunks += 1

            progress.update(task, description=f"Scanned {total_chunks} chunks, {len(documents)} docs")

            if offset is None:
                break

    console.print()
    console.print(f"Found {len(documents)} documents needing summaries")

    if not documents:
        console.print("[green]No migration needed - all documents have summaries![/green]")
        return

    if dry_run:
        console.print()
        console.print("[yellow]Dry run - would create summaries for:[/yellow]")
        for doc_id, doc in list(documents.items())[:20]:
            console.print(f"  - {doc['filename']} ({len(doc['chunks'])} chunks)")
        if len(documents) > 20:
            console.print(f"  ... and {len(documents) - 20} more")
        return

    # Create summaries
    console.print()
    console.print("Creating summaries...")
    created = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("Creating summaries...", total=len(documents))

        for doc_id, doc in documents.items():
            try:
                # Build summary text
                summary_parts = [
                    f"Document: {doc['filename'] or 'Unknown'}",
                    f"Namespace: {doc['namespace']}"
                ]

                if doc["headings"]:
                    summary_parts.append(f"Headings: {', '.join(doc['headings'][:20])}")

                # Add first ~1500 chars of content for better semantic matching
                content_preview = ""
                char_count = 0
                for chunk in doc["chunks"]:
                    remaining = 1500 - char_count
                    if remaining <= 0:
                        break
                    content_preview += chunk[:remaining] + " "
                    char_count += len(chunk[:remaining])

                if content_preview.strip():
                    summary_parts.append("")
                    summary_parts.append(content_preview.strip())

                summary_text = "\n".join(summary_parts)

                # Generate embedding
                summary_embedding = pipeline.embedding_provider.embed(summary_text)

                # Create summary record - use new UUID (Qdrant requires valid UUID or integer)
                import uuid
                summary_id = str(uuid.uuid4())
                summary_metadata = {
                    "_type": "document_summary",
                    "doc_id": doc_id,
                    "filename": doc["filename"],
                    "namespace": doc["namespace"],
                    "headings": doc["headings"][:50],
                    "chunk_count": len(doc["chunks"]),
                    "created_at": doc["created_at"] or datetime.now(timezone.utc).isoformat(),
                }

                # Insert summary
                vectordb.insert(
                    vectors=[summary_embedding],
                    texts=[summary_text],
                    metadatas=[summary_metadata],
                    ids=[summary_id],
                    namespace=doc["namespace"]
                )

                created += 1
                progress.update(task, advance=1, description=f"Created {created} summaries")

            except Exception as e:
                errors += 1
                logger.error(f"Failed to create summary for {doc_id}: {e}")
                progress.update(task, advance=1)

    console.print()
    console.print(f"[green]Created {created} summaries[/green]")
    if errors:
        console.print(f"[yellow]Errors: {errors}[/yellow]")
