"""CLI command for backfilling document index from vector database

This script iterates through documents with summaries in the vector database
and creates corresponding entries in the document index (DynamoDB). This is
useful for:

1. Initial migration from vector DB to document index
2. Rebuilding the index if corrupted
3. Recovering from index failures

The backfill script:
- Queries vector DB for all document summaries
- Extracts metadata and chunk IDs
- Creates entries in the document index
- Provides progress reporting and error handling
- Supports dry-run mode to preview changes
- Supports batch processing for large datasets
"""

import logging
import sys
from typing import Any

import click

# Setup logging before importing pipeline modules
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool):
    """Configure logging based on verbosity"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )


@click.command()
@click.option(
    '--namespace',
    '-n',
    default=None,
    help='Target namespace to backfill (if not provided, backfills all namespaces)'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Show what would be backfilled without making changes'
)
@click.option(
    '--batch-size',
    '-b',
    type=int,
    default=100,
    help='Number of documents to process in each batch (default: 100)'
)
@click.option(
    '--verbose',
    '-v',
    is_flag=True,
    help='Verbose output including individual document processing'
)
@click.option(
    '--skip-errors',
    is_flag=True,
    help='Continue processing on errors instead of stopping'
)
def backfill_document_index(
    namespace: str | None,
    dry_run: bool,
    batch_size: int,
    verbose: bool,
    skip_errors: bool
):
    """Backfill document index from vector database.

    This command scans the vector database for document summaries and creates
    corresponding entries in the document index. This is useful after deploying
    the document index feature or recovering from index failures.

    Examples:

        # Backfill all documents across all namespaces
        stache backfill-index

        # Backfill only a specific namespace
        stache backfill-index --namespace my-docs

        # Preview what would be backfilled
        stache backfill-index --dry-run

        # Backfill with smaller batches
        stache backfill-index --batch-size 50

        # Continue even if some documents fail
        stache backfill-index --skip-errors
    """
    setup_logging(verbose)

    # Validate batch size
    if batch_size < 1:
        click.echo("Error: batch-size must be at least 1", err=True)
        sys.exit(1)

    # Show dry-run notice
    if dry_run:
        click.echo("[DRY RUN] No changes will be made to the document index.\n")

    # Import pipeline and providers (lazy import to speed up --help)
    click.echo("Initializing pipeline...")
    try:
        from stache_ai.rag.pipeline import get_pipeline
        pipeline = get_pipeline()
    except Exception as e:
        click.echo(f"Error initializing pipeline: {e}", err=True)
        sys.exit(1)

    # Get providers
    vector_db = pipeline.vectordb_provider
    doc_index = pipeline.document_index_provider

    if doc_index is None:
        click.echo("Error: Document index provider not available", err=True)
        sys.exit(1)

    click.echo(f"Vector DB Provider: {vector_db.get_name()}")
    click.echo(f"Document Index Provider: {doc_index.get_name()}")
    if namespace:
        click.echo(f"Target Namespace: {namespace}")
    click.echo(f"Batch Size: {batch_size}\n")

    # Step 1: Collect all document summaries from vector DB
    click.echo("Scanning vector database for document summaries...")

    try:
        documents = _collect_documents(
            vector_db,
            namespace,
            verbose
        )
    except Exception as e:
        click.echo(f"Error scanning vector database: {e}", err=True)
        logger.exception("Failed to collect documents")
        sys.exit(1)

    if not documents:
        click.echo("No documents with summaries found in vector database.", err=True)
        sys.exit(0)

    click.echo(f"Found {len(documents)} document(s) with summaries\n")

    if dry_run:
        # Show preview of what would be backfilled
        click.echo("[DRY RUN] Would backfill the following documents:")
        for i, doc in enumerate(documents[:10], 1):
            click.echo(
                f"  {i}. {doc['filename']} in {doc['namespace']} "
                f"({doc['chunk_count']} chunks)"
            )
        if len(documents) > 10:
            click.echo(f"  ... and {len(documents) - 10} more")
        click.echo()

        # Summary
        click.echo("[DRY RUN] Summary:")
        click.echo(f"  Total documents to backfill: {len(documents)}")
        click.echo(f"  Total chunks: {sum(d['chunk_count'] for d in documents)}")
        sys.exit(0)

    # Step 2: Confirm before proceeding with actual backfill
    total_chunks = sum(d['chunk_count'] for d in documents)
    if not click.confirm(
        f"\nBackfill {len(documents)} document(s) with {total_chunks} total chunks?"
    ):
        click.echo("Aborted.")
        sys.exit(0)

    # Step 3: Backfill in batches
    click.echo()
    success_count = 0
    error_count = 0
    skipped_count = 0

    # Process documents with progress bar
    with click.progressbar(
        length=len(documents),
        label='Backfilling',
        show_pos=True,
        show_percent=True
    ) as progress_bar:
        for batch_idx in range(0, len(documents), batch_size):
            batch = documents[batch_idx:batch_idx + batch_size]

            for doc in batch:
                result = _backfill_document(
                    doc,
                    doc_index,
                    skip_errors,
                    verbose
                )

                if result['status'] == 'success':
                    success_count += 1
                    logger.debug(f"Backfilled {doc['filename']}")
                elif result['status'] == 'skipped':
                    skipped_count += 1
                    logger.warning(
                        f"Skipped {doc['filename']}: {result.get('reason', 'unknown')}"
                    )
                else:  # error
                    error_count += 1
                    logger.error(
                        f"Failed {doc['filename']}: {result.get('error', 'unknown error')}"
                    )

                progress_bar.update(1)

                # Stop on first error unless skip_errors is set
                if result['status'] == 'error' and not skip_errors:
                    progress_bar.finish()
                    click.echo(
                        f"\nError backfilling {doc['filename']}: "
                        f"{result.get('error', 'unknown error')}",
                        err=True
                    )
                    click.echo(
                        "Use --skip-errors to continue on failures.",
                        err=True
                    )
                    sys.exit(1)

    # Step 4: Summary
    click.echo(f"\n{'='*50}")
    click.echo("Backfill complete!")
    click.echo(f"  Successful: {success_count} document(s)")
    click.echo(f"  Skipped: {skipped_count} document(s)")
    click.echo(f"  Failed: {error_count} document(s)")
    click.echo(f"  Total chunks indexed: {sum(d['chunk_count'] for d in documents[:success_count])}")

    if error_count > 0:
        sys.exit(1)


def _collect_documents(
    vector_db,
    namespace: str | None,
    verbose: bool
) -> list[dict[str, Any]]:
    """Collect all documents with summaries from vector database.

    Args:
        vector_db: Vector DB provider instance
        namespace: Optional namespace filter
        verbose: If True, log individual documents found

    Returns:
        List of document dictionaries with metadata and chunk IDs
    """
    documents = []

    # Build filter for document summaries
    filter_dict = {"_type": "document_summary"}

    # List all document summaries with pagination
    last_key = None
    limit = 1000  # S3 Vectors page size

    while True:
        try:
            results = vector_db.list_by_filter(
                filter=filter_dict,
                limit=limit
            )

            if not results:
                break

            for result in results:
                # Extract document metadata
                # Note: Qdrant returns metadata fields at top level, not nested under 'metadata'
                doc_namespace = _extract_string(result.get('namespace'))
                doc_filename = _extract_string(result.get('filename', 'unknown'))
                doc_id = _extract_string(result.get('doc_id'))

                # Skip if namespace filter doesn't match
                if namespace and doc_namespace != namespace:
                    continue

                # Get chunk IDs for this document
                if doc_id and doc_namespace:
                    try:
                        chunk_ids = vector_db.list_by_filter(
                            filter={"doc_id": doc_id, "_type": {"$ne": "document_summary"}},
                            limit=10000
                        )
                        chunk_count = len(chunk_ids)
                    except Exception:
                        # Fallback: assume we have some chunks
                        chunk_count = _extract_int(result.get('chunk_count', 0))

                    if chunk_count == 0:
                        chunk_count = _extract_int(result.get('chunk_count', 0))
                else:
                    chunk_count = _extract_int(result.get('chunk_count', 0))

                # Extract optional fields
                summary = _extract_string(result.get('summary'))
                summary_embedding_id = _extract_string(result.get('summary_embedding_id'))
                file_type = _extract_string(result.get('file_type'))
                file_size = _extract_int(result.get('file_size'))
                headings = _extract_list(result.get('headings'))

                # Build document record
                doc_record = {
                    'doc_id': doc_id or result.get('key', f"unknown-{len(documents)}"),
                    'filename': doc_filename,
                    'namespace': doc_namespace,
                    'chunk_count': chunk_count,
                    'summary': summary,
                    'summary_embedding_id': summary_embedding_id,
                    'file_type': file_type,
                    'file_size': file_size,
                    'headings': headings,
                    'chunk_ids': []  # Will be populated during backfill
                }

                documents.append(doc_record)
                if verbose:
                    logger.debug(
                        f"Found: {doc_filename} in {doc_namespace} "
                        f"({chunk_count} chunks)"
                    )

            # Check if there are more results
            if len(results) < limit:
                break

        except Exception as e:
            logger.error(f"Error listing documents: {e}")
            raise

    return documents


def _backfill_document(
    doc: dict[str, Any],
    doc_index,
    skip_errors: bool,
    verbose: bool
) -> dict[str, str]:
    """Backfill a single document into the document index.

    Args:
        doc: Document record to backfill
        doc_index: Document index provider instance
        skip_errors: If True, don't raise exceptions
        verbose: If True, log debug info

    Returns:
        Dictionary with keys:
        - status: 'success', 'skipped', or 'error'
        - reason: (if skipped) reason for skipping
        - error: (if error) error message
    """
    try:
        # Validate required fields
        if not doc.get('doc_id'):
            return {'status': 'skipped', 'reason': 'Missing doc_id'}
        if not doc.get('filename'):
            return {'status': 'skipped', 'reason': 'Missing filename'}
        if not doc.get('namespace'):
            return {'status': 'skipped', 'reason': 'Missing namespace'}

        # Check if document already exists
        if doc_index.document_exists(doc['filename'], doc['namespace']):
            return {'status': 'skipped', 'reason': 'Document already exists in index'}

        # Create document index entry
        doc_index.create_document(
            doc_id=doc['doc_id'],
            filename=doc['filename'],
            namespace=doc['namespace'],
            chunk_ids=doc.get('chunk_ids', []),
            summary=doc.get('summary'),
            summary_embedding_id=doc.get('summary_embedding_id'),
            headings=doc.get('headings'),
            file_type=doc.get('file_type'),
            file_size=doc.get('file_size')
        )

        if verbose:
            logger.debug(f"Created index entry for {doc['filename']}")

        return {'status': 'success'}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error backfilling {doc.get('filename', 'unknown')}: {error_msg}")

        if skip_errors:
            return {'status': 'error', 'error': error_msg}
        else:
            raise


def _extract_string(value: Any) -> str | None:
    """Extract string value from metadata with type checking."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bool):
        return str(value)
    return str(value)


def _extract_int(value: Any) -> int:
    """Extract integer value from metadata with type checking."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _extract_list(value: Any) -> list[str] | None:
    """Extract list value from metadata with type checking."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    return None


if __name__ == '__main__':
    backfill_document_index()
