"""CLI command for dumping/exporting the vector database"""

import json
import sys
from datetime import datetime
from pathlib import Path

import click


@click.command()
@click.option('--output', '-o', type=click.Path(path_type=Path),
              help='Output file path (default: stdout or stache-dump-<timestamp>.json)')
@click.option('--namespace', '-n', help='Only dump specific namespace (supports wildcards like "books/*")')
@click.option('--format', '-f', 'fmt', type=click.Choice(['json', 'jsonl']), default='json',
              help='Output format (default: json)')
@click.option('--include-vectors', is_flag=True, help='Include embedding vectors (large!)')
@click.option('--pretty', is_flag=True, help='Pretty-print JSON output')
def dump_database(
    output: Path | None,
    namespace: str | None,
    fmt: str,
    include_vectors: bool,
    pretty: bool
):
    """
    Dump/export the vector database contents.

    Exports all chunks with their text and metadata. Useful for:
    - Backing up before switching embedding dimensions
    - Migrating to a different vector database
    - Inspecting database contents

    Examples:

        # Dump everything to stdout
        stache dump

        # Dump to a file
        stache dump -o backup.json

        # Dump specific namespace
        stache dump -n books/fiction -o fiction.json

        # Dump as JSON Lines (one record per line)
        stache dump -f jsonl -o backup.jsonl

        # Include vectors (warning: large file)
        stache dump --include-vectors -o full-backup.json
    """
    import stache_ai.providers.vectordb  # noqa - registers providers
    from stache_ai.config import settings
    from stache_ai.providers.factories import VectorDBProviderFactory

    click.echo("Connecting to vector database...", err=True)
    vectordb = VectorDBProviderFactory.create(settings)

    # Provider check
    if "export" not in vectordb.capabilities:
        click.echo("ERROR: Database dump currently requires Qdrant provider.", err=True)
        click.echo("S3 Vectors support coming in Phase 2 with improved export functionality.", err=True)
        return

    # Get collection info
    info = vectordb.get_collection_info()
    click.echo(f"Collection: {info['name']}, Points: {info.get('points_count', 'unknown')}", err=True)

    # Scroll through all points
    click.echo("Exporting...", err=True)

    all_points = []
    offset = None
    batch_size = 100
    total_exported = 0

    # Build filter if namespace specified
    scroll_filter = None
    if namespace and not namespace.endswith("/*"):
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        scroll_filter = Filter(
            must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
        )

    # For wildcard namespaces, we'll filter in Python
    namespace_prefix = None
    if namespace and namespace.endswith("/*"):
        namespace_prefix = namespace[:-2]

    while True:
        points, offset = vectordb.client.scroll(
            collection_name=vectordb.collection_name,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=include_vectors
        )

        if not points:
            break

        for point in points:
            # Filter for wildcard namespace
            point_namespace = point.payload.get("namespace", "default")
            if namespace_prefix:
                if not (point_namespace.startswith(namespace_prefix + "/") or
                        point_namespace == namespace_prefix):
                    continue

            record = {
                "id": str(point.id),
                "text": point.payload.get("text", ""),
                "namespace": point_namespace,
                "metadata": {k: v for k, v in point.payload.items()
                            if k not in ("text", "namespace")}
            }

            if include_vectors and point.vector:
                record["vector"] = point.vector

            all_points.append(record)
            total_exported += 1

        click.echo(f"  Exported {total_exported} chunks...", err=True)

        if offset is None:
            break

    click.echo(f"Total: {total_exported} chunks exported", err=True)

    # Prepare output
    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "collection": info['name'],
        "namespace_filter": namespace,
        "total_chunks": total_exported,
        "includes_vectors": include_vectors,
        "chunks": all_points
    }

    # Determine output destination
    if output is None and fmt == 'json':
        # Default filename if not stdout
        if sys.stdout.isatty():
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output = Path(f"stache-dump-{timestamp}.json")
            click.echo(f"Writing to {output}", err=True)

    # Write output
    if fmt == 'jsonl':
        # JSON Lines format - one record per line
        def write_jsonl(f):
            for chunk in all_points:
                f.write(json.dumps(chunk) + "\n")

        if output:
            with open(output, 'w') as f:
                write_jsonl(f)
        else:
            write_jsonl(sys.stdout)
    else:
        # Standard JSON
        indent = 2 if pretty else None
        json_str = json.dumps(export_data, indent=indent)

        if output:
            with open(output, 'w') as f:
                f.write(json_str)
        else:
            click.echo(json_str)

    if output:
        click.echo(f"Done! Exported to {output}", err=True)


if __name__ == '__main__':
    dump_database()
