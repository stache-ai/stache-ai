"""Export namespaces from Redis for migration to other providers (e.g., MongoDB).

This script connects directly to Redis and exports all namespaces,
regardless of the current NAMESPACE_PROVIDER setting.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


@click.command()
@click.argument('output', type=click.Path(path_type=Path), required=False)
@click.option('--host', '-h', default='localhost', help='Redis host (default: localhost)')
@click.option('--port', '-p', type=int, default=6379, help='Redis port (default: 6379)')
@click.option('--password', '-a', default=None, help='Redis password')
@click.option('--db', '-d', type=int, default=0, help='Redis database number (default: 0)')
@click.option('--pretty', is_flag=True, help='Pretty-print JSON output')
def redis_export(output: Path | None, host: str, port: int, password: str | None, db: int, pretty: bool):
    """
    Export all namespaces from Redis to a JSON file.

    This command connects directly to Redis, bypassing the configured
    NAMESPACE_PROVIDER. Useful for migrating from Redis to MongoDB or
    other providers.

    If OUTPUT is not specified, prints to stdout.

    Examples:
        stache redis-export namespaces.json
        stache redis-export --host redis.example.com namespaces.json
        stache redis-export --pretty  # print to stdout
        stache redis-export -h localhost -p 6379 -d 0 backup.json
    """
    import redis

    # Connect to Redis
    console.print(f"[bold]Connecting to Redis:[/bold] {host}:{port} (db={db})")

    try:
        client = redis.Redis(
            host=host,
            port=port,
            password=password or None,
            db=db,
            decode_responses=True
        )
        client.ping()
        console.print("[green]Connected successfully[/green]")
    except redis.ConnectionError as e:
        console.print(f"[red]Failed to connect to Redis: {e}[/red]")
        raise click.Abort()

    # Redis key patterns (from redis_provider.py)
    NS_KEY_PREFIX = "stache:namespace:"
    NS_INDEX_KEY = "stache:namespaces"

    # Get all namespace IDs
    all_ids = client.smembers(NS_INDEX_KEY)

    if not all_ids:
        console.print("[yellow]No namespaces found in Redis.[/yellow]")
        return

    console.print(f"[bold]Found:[/bold] {len(all_ids)} namespaces")

    # Fetch all namespaces
    namespaces = []
    for ns_id in sorted(all_ids):
        key = f"{NS_KEY_PREFIX}{ns_id}"
        data = client.get(key)
        if data:
            try:
                ns = json.loads(data)
                # Ensure metadata is a dict
                if isinstance(ns.get("metadata"), str):
                    ns["metadata"] = json.loads(ns["metadata"])
                # Ensure filter_keys exists
                if "filter_keys" not in ns:
                    ns["filter_keys"] = []
                namespaces.append(ns)
            except json.JSONDecodeError as e:
                console.print(f"[yellow]Warning: Failed to parse namespace {ns_id}: {e}[/yellow]")

    # Build export data
    export_data = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "redis",
            "host": host,
            "port": port,
            "db": db
        },
        "count": len(namespaces),
        "namespaces": namespaces
    }

    # Format output
    if pretty:
        output_str = json.dumps(export_data, indent=2, ensure_ascii=False)
    else:
        output_str = json.dumps(export_data, ensure_ascii=False)

    # Write or print
    if output:
        output.write_text(output_str, encoding='utf-8')
        console.print(f"[green]Exported {len(namespaces)} namespaces to {output}[/green]")
    else:
        console.print(output_str)

    # Show summary
    console.print()
    console.print("[bold]Namespace summary:[/bold]")
    root_count = sum(1 for ns in namespaces if ns.get("parent_id") is None)
    child_count = len(namespaces) - root_count
    console.print(f"  Root namespaces: {root_count}")
    console.print(f"  Child namespaces: {child_count}")

    # Show hierarchy preview
    if namespaces:
        console.print()
        console.print("[bold]Hierarchy preview:[/bold]")
        for ns in sorted(namespaces, key=lambda x: x["id"])[:10]:
            indent = "  " * ns["id"].count("/")
            console.print(f"  {indent}[cyan]{ns['id']}[/cyan] - {ns['name']}")
        if len(namespaces) > 10:
            console.print(f"  ... and {len(namespaces) - 10} more")


if __name__ == '__main__':
    redis_export()
