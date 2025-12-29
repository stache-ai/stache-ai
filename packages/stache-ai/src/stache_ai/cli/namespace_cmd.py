"""Namespace import/export commands for backup and migration."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()


def get_namespace_provider():
    """Get the configured namespace provider."""
    from stache_ai.config import settings
    from stache_ai.providers import NamespaceProviderFactory
    return NamespaceProviderFactory.create(settings)


def get_settings():
    """Get settings lazily."""
    from stache_ai.config import settings
    return settings


@click.command()
@click.argument('output', type=click.Path(path_type=Path), required=False)
@click.option('--format', '-f', 'fmt', type=click.Choice(['json', 'jsonl']), default='json',
              help='Output format (json=single file, jsonl=one per line)')
@click.option('--pretty', is_flag=True, help='Pretty-print JSON output')
def export_namespaces(output: Path | None, fmt: str, pretty: bool):
    """
    Export all namespaces to a JSON file.

    If OUTPUT is not specified, prints to stdout.

    Examples:
        stache namespace-export namespaces.json
        stache namespace-export --format jsonl namespaces.jsonl
        stache namespace-export --pretty  # print to stdout
    """
    provider = get_namespace_provider()

    # Get all namespaces
    namespaces = provider.list(include_children=True)

    if not namespaces:
        console.print("[yellow]No namespaces found to export.[/yellow]")
        return

    # Build export data
    export_data = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "provider": get_settings().namespace_provider,
        "count": len(namespaces),
        "namespaces": namespaces
    }

    # Format output
    if fmt == 'json':
        if pretty:
            output_str = json.dumps(export_data, indent=2, ensure_ascii=False)
        else:
            output_str = json.dumps(export_data, ensure_ascii=False)
    else:  # jsonl
        lines = [json.dumps(export_data | {"namespaces": None}, ensure_ascii=False)]
        for ns in namespaces:
            lines.append(json.dumps(ns, ensure_ascii=False))
        output_str = "\n".join(lines)

    # Write or print
    if output:
        output.write_text(output_str, encoding='utf-8')
        console.print(f"[green]Exported {len(namespaces)} namespaces to {output}[/green]")
    else:
        console.print(output_str)


@click.command()
@click.argument('input_file', type=click.Path(exists=True, path_type=Path))
@click.option('--dry-run', is_flag=True, help='Show what would be imported without making changes')
@click.option('--skip-existing', is_flag=True, help='Skip namespaces that already exist')
@click.option('--update-existing', is_flag=True, help='Update existing namespaces with imported data')
def import_namespaces(input_file: Path, dry_run: bool, skip_existing: bool, update_existing: bool):
    """
    Import namespaces from a JSON file.

    Examples:
        stache namespace-import namespaces.json
        stache namespace-import --dry-run namespaces.json
        stache namespace-import --skip-existing namespaces.json
        stache namespace-import --update-existing namespaces.json
    """
    if skip_existing and update_existing:
        console.print("[red]Cannot use both --skip-existing and --update-existing[/red]")
        return

    provider = get_namespace_provider()

    # Read input file
    content = input_file.read_text(encoding='utf-8')

    # Parse based on format
    if input_file.suffix == '.jsonl':
        lines = content.strip().split('\n')
        # First line is metadata
        metadata = json.loads(lines[0])
        namespaces = [json.loads(line) for line in lines[1:]]
    else:
        data = json.loads(content)
        metadata = {k: v for k, v in data.items() if k != 'namespaces'}
        namespaces = data.get('namespaces', [])

    if not namespaces:
        console.print("[yellow]No namespaces found in import file.[/yellow]")
        return

    console.print(f"[bold]Import file:[/bold] {input_file}")
    console.print(f"[bold]Exported from:[/bold] {metadata.get('provider', 'unknown')}")
    console.print(f"[bold]Exported at:[/bold] {metadata.get('exported_at', 'unknown')}")
    console.print(f"[bold]Namespaces:[/bold] {len(namespaces)}")
    console.print()

    # Sort by hierarchy depth (parents before children)
    def get_depth(ns):
        return ns['id'].count('/')
    namespaces.sort(key=get_depth)

    # Process namespaces
    created = 0
    updated = 0
    skipped = 0
    errors = []

    table = Table(title="Import Results" if not dry_run else "Dry Run - Would Import")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Action")
    table.add_column("Status")

    for ns in namespaces:
        ns_id = ns['id']
        exists = provider.exists(ns_id)

        if exists:
            if skip_existing:
                table.add_row(ns_id, ns['name'], "Skip", "[yellow]exists[/yellow]")
                skipped += 1
                continue
            elif update_existing:
                if dry_run:
                    table.add_row(ns_id, ns['name'], "Update", "[blue]would update[/blue]")
                    updated += 1
                else:
                    try:
                        provider.update(
                            id=ns_id,
                            name=ns.get('name'),
                            description=ns.get('description'),
                            metadata=ns.get('metadata')
                        )
                        table.add_row(ns_id, ns['name'], "Update", "[green]updated[/green]")
                        updated += 1
                    except Exception as e:
                        table.add_row(ns_id, ns['name'], "Update", f"[red]error: {e}[/red]")
                        errors.append({"id": ns_id, "error": str(e)})
            else:
                table.add_row(ns_id, ns['name'], "Skip", "[yellow]exists (use --skip-existing or --update-existing)[/yellow]")
                skipped += 1
        else:
            if dry_run:
                table.add_row(ns_id, ns['name'], "Create", "[blue]would create[/blue]")
                created += 1
            else:
                try:
                    provider.create(
                        id=ns_id,
                        name=ns['name'],
                        description=ns.get('description', ''),
                        parent_id=ns.get('parent_id'),
                        metadata=ns.get('metadata')
                    )
                    table.add_row(ns_id, ns['name'], "Create", "[green]created[/green]")
                    created += 1
                except Exception as e:
                    table.add_row(ns_id, ns['name'], "Create", f"[red]error: {e}[/red]")
                    errors.append({"id": ns_id, "error": str(e)})

    console.print(table)
    console.print()

    if dry_run:
        console.print(f"[bold]Would create:[/bold] {created}")
        console.print(f"[bold]Would update:[/bold] {updated}")
        console.print(f"[bold]Would skip:[/bold] {skipped}")
    else:
        console.print(f"[bold]Created:[/bold] {created}")
        console.print(f"[bold]Updated:[/bold] {updated}")
        console.print(f"[bold]Skipped:[/bold] {skipped}")
        if errors:
            console.print(f"[bold red]Errors:[/bold red] {len(errors)}")


@click.command()
def list_namespaces():
    """
    List all namespaces in a tree view.
    """
    provider = get_namespace_provider()
    tree = provider.get_tree()

    if not tree:
        console.print("[yellow]No namespaces found.[/yellow]")
        console.print(f"[dim]Provider: {get_settings().namespace_provider}[/dim]")
        return

    console.print(f"[bold]Namespace Tree[/bold] (provider: {get_settings().namespace_provider})")
    console.print()

    def print_tree(nodes, indent=0):
        for node in nodes:
            prefix = "  " * indent + ("├─ " if indent > 0 else "")
            console.print(f"{prefix}[cyan]{node['id']}[/cyan] - {node['name']}")
            if node.get('description'):
                desc_prefix = "  " * indent + ("│  " if indent > 0 else "  ")
                console.print(f"{desc_prefix}[dim]{node['description']}[/dim]")
            if node.get('children'):
                print_tree(node['children'], indent + 1)

    print_tree(tree)

    # Count total
    total = len(provider.list(include_children=True))
    console.print()
    console.print(f"[bold]Total:[/bold] {total} namespaces")
