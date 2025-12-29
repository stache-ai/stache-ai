"""Inspect vectors in the database and optionally create document index entries.

This script provides tools to:
- View vector database statistics
- List vectors with filtering
- Group vectors by document ID
- Create document index entries from existing vectors
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()


def setup_logging(verbose: bool):
    """Configure logging based on verbosity"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )


@click.group()
def vectors():
    """Vector database inspection and document creation tools."""
    pass


@vectors.command(name='stats')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def vectors_stats(verbose: bool):
    """Show vector database statistics."""
    setup_logging(verbose)

    console.print("[bold]Initializing pipeline...[/bold]")
    try:
        from stache_ai.rag.pipeline import get_pipeline
        pipeline = get_pipeline()
    except Exception as e:
        console.print(f"[red]Error initializing pipeline: {e}[/red]")
        sys.exit(1)

    vector_db = pipeline.vectordb_provider
    console.print(f"[bold]Vector DB Provider:[/bold] {vector_db.get_name()}")
    console.print()

    # Get collection info
    try:
        info = vector_db.get_collection_info()
        console.print("[bold]Collection Info:[/bold]")
        for key, value in info.items():
            console.print(f"  {key}: {value}")
    except Exception as e:
        console.print(f"[yellow]Could not get collection info: {e}[/yellow]")

    # Count vectors by type
    console.print()
    console.print("[bold]Vector Counts by Type:[/bold]")

    try:
        # Count regular chunks (exclude summaries)
        total_chunks = vector_db.count_by_filter({})
        console.print(f"  Total vectors: {total_chunks}")

        # Count document summaries
        summary_count = vector_db.count_by_filter({"_type": "document_summary"})
        console.print(f"  Document summaries: {summary_count}")
        console.print(f"  Regular chunks: {total_chunks - summary_count}")
    except NotImplementedError:
        console.print("  [yellow]count_by_filter not supported by this provider[/yellow]")
    except Exception as e:
        console.print(f"  [red]Error counting vectors: {e}[/red]")


@vectors.command(name='list')
@click.option('--namespace', '-n', default=None, help='Filter by namespace')
@click.option('--doc-id', '-d', default=None, help='Filter by document ID')
@click.option('--type', '-t', 'vector_type', default=None, help='Filter by _type (e.g., document_summary)')
@click.option('--limit', '-l', type=int, default=100, help='Maximum results (default: 100)')
@click.option('--output', '-o', type=click.Path(path_type=Path), help='Output to JSON file')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def vectors_list(
    namespace: str | None,
    doc_id: str | None,
    vector_type: str | None,
    limit: int,
    output: Path | None,
    verbose: bool
):
    """List vectors with optional filtering."""
    setup_logging(verbose)

    console.print("[bold]Initializing pipeline...[/bold]")
    try:
        from stache_ai.rag.pipeline import get_pipeline
        pipeline = get_pipeline()
    except Exception as e:
        console.print(f"[red]Error initializing pipeline: {e}[/red]")
        sys.exit(1)

    vector_db = pipeline.vectordb_provider

    # Build filter
    filter_dict = {}
    if namespace:
        filter_dict['namespace'] = namespace
    if doc_id:
        filter_dict['doc_id'] = doc_id
    if vector_type:
        filter_dict['_type'] = vector_type

    console.print(f"[bold]Filter:[/bold] {filter_dict or '(none)'}")
    console.print(f"[bold]Limit:[/bold] {limit}")
    console.print()

    try:
        results = vector_db.list_by_filter(filter=filter_dict, limit=limit)
    except NotImplementedError:
        console.print("[red]list_by_filter not supported by this provider[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error listing vectors: {e}[/red]")
        sys.exit(1)

    console.print(f"[bold]Found:[/bold] {len(results)} vectors")

    if output:
        # Write to JSON file
        output.write_text(json.dumps(results, indent=2, default=str), encoding='utf-8')
        console.print(f"[green]Saved to {output}[/green]")
    else:
        # Display in table
        if results:
            table = Table(title="Vectors")
            table.add_column("ID", style="cyan", max_width=20)
            table.add_column("Namespace", style="green")
            table.add_column("Filename", max_width=30)
            table.add_column("Doc ID", max_width=15)
            table.add_column("Type")

            for r in results[:50]:  # Limit display to 50
                table.add_row(
                    str(r.get('key', r.get('id', 'N/A')))[:20],
                    r.get('namespace', 'N/A'),
                    r.get('filename', 'N/A')[:30] if r.get('filename') else 'N/A',
                    str(r.get('doc_id', 'N/A'))[:15] if r.get('doc_id') else 'N/A',
                    r.get('_type', 'chunk')
                )

            console.print(table)
            if len(results) > 50:
                console.print(f"  ... and {len(results) - 50} more (use --output to see all)")


@vectors.command(name='documents')
@click.option('--namespace', '-n', default=None, help='Filter by namespace')
@click.option('--output', '-o', type=click.Path(path_type=Path), help='Output to JSON file')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def vectors_documents(
    namespace: str | None,
    output: Path | None,
    verbose: bool
):
    """Group vectors by document ID to discover documents.

    This command scans the vector database and groups vectors by their
    doc_id metadata field, showing what documents exist in the database.
    """
    setup_logging(verbose)

    console.print("[bold]Initializing pipeline...[/bold]")
    try:
        from stache_ai.rag.pipeline import get_pipeline
        pipeline = get_pipeline()
    except Exception as e:
        console.print(f"[red]Error initializing pipeline: {e}[/red]")
        sys.exit(1)

    vector_db = pipeline.vectordb_provider

    # Build filter
    filter_dict = {}
    if namespace:
        filter_dict['namespace'] = namespace

    console.print("[bold]Scanning vectors...[/bold]")

    try:
        # Get all vectors (may need pagination for large datasets)
        results = vector_db.list_by_filter(filter=filter_dict, limit=100000)
    except NotImplementedError:
        console.print("[red]list_by_filter not supported by this provider[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error listing vectors: {e}[/red]")
        sys.exit(1)

    # Group by doc_id
    documents: dict[str, dict[str, Any]] = defaultdict(lambda: {
        'chunk_count': 0,
        'has_summary': False,
        'namespace': None,
        'filename': None,
        'summary_id': None
    })

    no_doc_id_count = 0

    for r in results:
        doc_id = r.get('doc_id')
        if not doc_id:
            no_doc_id_count += 1
            continue

        doc = documents[doc_id]
        doc['namespace'] = r.get('namespace') or doc['namespace']
        doc['filename'] = r.get('filename') or doc['filename']

        if r.get('_type') == 'document_summary':
            doc['has_summary'] = True
            doc['summary_id'] = r.get('key', r.get('id'))
        else:
            doc['chunk_count'] += 1

    console.print(f"[bold]Found:[/bold] {len(documents)} unique documents")
    console.print(f"[bold]Vectors without doc_id:[/bold] {no_doc_id_count}")
    console.print()

    # Convert to list for output
    doc_list = [
        {
            'doc_id': doc_id,
            **data
        }
        for doc_id, data in sorted(documents.items())
    ]

    if output:
        export_data = {
            'exported_at': datetime.now(timezone.utc).isoformat(),
            'namespace_filter': namespace,
            'total_documents': len(doc_list),
            'vectors_without_doc_id': no_doc_id_count,
            'documents': doc_list
        }
        output.write_text(json.dumps(export_data, indent=2, default=str), encoding='utf-8')
        console.print(f"[green]Saved to {output}[/green]")
    else:
        # Display summary table
        table = Table(title="Documents in Vector Database")
        table.add_column("Doc ID", style="cyan", max_width=20)
        table.add_column("Namespace", style="green")
        table.add_column("Filename", max_width=35)
        table.add_column("Chunks", justify="right")
        table.add_column("Summary", justify="center")

        for doc in doc_list[:50]:
            table.add_row(
                str(doc['doc_id'])[:20],
                doc['namespace'] or 'N/A',
                (doc['filename'] or 'N/A')[:35],
                str(doc['chunk_count']),
                "[green]Yes[/green]" if doc['has_summary'] else "[yellow]No[/yellow]"
            )

        console.print(table)
        if len(doc_list) > 50:
            console.print(f"  ... and {len(doc_list) - 50} more (use --output to see all)")

    # Summary
    console.print()
    with_summary = sum(1 for d in doc_list if d['has_summary'])
    without_summary = len(doc_list) - with_summary
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Documents with summaries: {with_summary}")
    console.print(f"  Documents without summaries: {without_summary}")


@vectors.command(name='create-index')
@click.option('--namespace', '-n', default=None, help='Filter by namespace')
@click.option('--dry-run', is_flag=True, help='Preview changes without creating entries')
@click.option('--skip-existing', is_flag=True, default=True, help='Skip documents that already exist in index (default: True)')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def vectors_create_index(
    namespace: str | None,
    dry_run: bool,
    skip_existing: bool,
    verbose: bool
):
    """Create document index entries from vectors.

    This command scans the vector database, groups vectors by doc_id,
    and creates corresponding entries in the document index. This is
    useful when you have vectors but no document index entries.

    Unlike backfill-index which requires document summaries, this command
    creates index entries for all documents that have a doc_id, even if
    they don't have summaries.
    """
    setup_logging(verbose)

    if dry_run:
        console.print("[yellow][DRY RUN] No changes will be made.[/yellow]")
        console.print()

    console.print("[bold]Initializing pipeline...[/bold]")
    try:
        from stache_ai.rag.pipeline import get_pipeline
        pipeline = get_pipeline()
    except Exception as e:
        console.print(f"[red]Error initializing pipeline: {e}[/red]")
        sys.exit(1)

    vector_db = pipeline.vectordb_provider
    doc_index = pipeline.document_index_provider

    if doc_index is None:
        console.print("[red]Error: Document index provider not available[/red]")
        sys.exit(1)

    console.print(f"[bold]Vector DB Provider:[/bold] {vector_db.get_name()}")
    console.print(f"[bold]Document Index Provider:[/bold] {doc_index.get_name()}")
    console.print()

    # Build filter
    filter_dict = {}
    if namespace:
        filter_dict['namespace'] = namespace

    console.print("[bold]Scanning vectors...[/bold]")

    try:
        results = vector_db.list_by_filter(filter=filter_dict, limit=100000)
    except NotImplementedError:
        console.print("[red]list_by_filter not supported by this provider[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error listing vectors: {e}[/red]")
        sys.exit(1)

    # Group by doc_id
    documents: dict[str, dict[str, Any]] = defaultdict(lambda: {
        'chunk_ids': [],
        'namespace': None,
        'filename': None,
        'summary': None,
        'summary_embedding_id': None,
        'headings': None,
        'file_type': None,
        'file_size': None
    })

    for r in results:
        doc_id = r.get('doc_id')
        if not doc_id:
            continue

        doc = documents[doc_id]
        doc['namespace'] = r.get('namespace') or doc['namespace']
        doc['filename'] = r.get('filename') or doc['filename']

        vector_id = r.get('key', r.get('id'))

        if r.get('_type') == 'document_summary':
            doc['summary'] = r.get('text') or r.get('summary')
            doc['summary_embedding_id'] = vector_id
            doc['headings'] = r.get('headings')
            doc['file_type'] = r.get('file_type')
            doc['file_size'] = r.get('file_size')
        else:
            if vector_id:
                doc['chunk_ids'].append(vector_id)

    console.print(f"[bold]Found:[/bold] {len(documents)} documents with doc_id")

    # Filter out documents that already exist
    to_create = []
    skipped = 0

    for doc_id, data in documents.items():
        if not data['namespace'] or not data['filename']:
            skipped += 1
            continue

        if skip_existing:
            try:
                exists = doc_index.document_exists(data['filename'], data['namespace'])
                if exists:
                    skipped += 1
                    continue
            except Exception:
                pass  # Proceed if we can't check

        to_create.append({'doc_id': doc_id, **data})

    console.print(f"[bold]To create:[/bold] {len(to_create)} new index entries")
    console.print(f"[bold]Skipped:[/bold] {skipped} (missing data or already exist)")
    console.print()

    if not to_create:
        console.print("[yellow]No documents to create.[/yellow]")
        return

    if dry_run:
        console.print("[yellow][DRY RUN] Would create the following entries:[/yellow]")
        for doc in to_create[:10]:
            console.print(f"  - {doc['filename']} in {doc['namespace']} ({len(doc['chunk_ids'])} chunks)")
        if len(to_create) > 10:
            console.print(f"  ... and {len(to_create) - 10} more")
        return

    # Confirm before proceeding
    if not click.confirm(f"Create {len(to_create)} document index entries?"):
        console.print("Aborted.")
        return

    # Create entries
    success = 0
    failed = 0

    with click.progressbar(to_create, label='Creating entries') as docs:
        for doc in docs:
            try:
                doc_index.create_document(
                    doc_id=doc['doc_id'],
                    filename=doc['filename'],
                    namespace=doc['namespace'],
                    chunk_ids=doc['chunk_ids'],
                    summary=doc['summary'],
                    summary_embedding_id=doc['summary_embedding_id'],
                    headings=doc['headings'],
                    file_type=doc['file_type'],
                    file_size=doc['file_size']
                )
                success += 1
            except Exception as e:
                failed += 1
                if verbose:
                    logger.error(f"Failed to create {doc['filename']}: {e}")

    console.print()
    console.print("[bold]Results:[/bold]")
    console.print(f"  [green]Created:[/green] {success}")
    console.print(f"  [red]Failed:[/red] {failed}")


if __name__ == '__main__':
    vectors()
