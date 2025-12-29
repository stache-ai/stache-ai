"""Main CLI entry point"""

from pathlib import Path

import click
from dotenv import load_dotenv

# Load .env file from current working directory before importing anything else
# This ensures environment variables are set before pydantic-settings reads them
_env_file = Path.cwd() / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


@click.group()
@click.version_option(version='0.1.0', prog_name='stache-admin')
def cli():
    """Stache Admin CLI - Database and provider management commands"""
    pass


def setup_cli():
    """Register all CLI commands"""
    from .backfill_document_index import backfill_document_index
    from .dump_cmd import dump_database
    from .import_cmd import import_directory
    from .migrate_cmd import migrate_summaries
    from .namespace_cmd import export_namespaces, import_namespaces, list_namespaces
    from .providers_cmd import providers
    from .redis_export import redis_export
    from .vectors_cmd import vectors

    cli.add_command(import_directory, name='import')
    cli.add_command(dump_database, name='dump')
    cli.add_command(migrate_summaries, name='migrate-summaries')
    cli.add_command(export_namespaces, name='namespace-export')
    cli.add_command(import_namespaces, name='namespace-import')
    cli.add_command(list_namespaces, name='namespace-list')
    cli.add_command(backfill_document_index, name='backfill-index')
    cli.add_command(redis_export, name='redis-export')
    cli.add_command(vectors, name='vectors')
    cli.add_command(providers, name='providers')


# Setup commands when module is imported
setup_cli()
