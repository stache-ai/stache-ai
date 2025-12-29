"""Providers diagnostic command"""

import click

from stache_ai.providers import plugin_loader


@click.command()
def providers():
    """List all discovered providers"""
    click.echo("Stache Provider Discovery\n")

    for provider_type, group in plugin_loader.PROVIDER_GROUPS.items():
        providers = plugin_loader.get_providers(provider_type)
        click.echo(f"{provider_type.upper()} Providers ({len(providers)}):")

        for name, cls in providers.items():
            module = cls.__module__
            click.echo(f"  - {name:15} ({module})")

        click.echo()

    total = sum(len(plugin_loader.get_providers(t)) for t in plugin_loader.PROVIDER_GROUPS)
    click.echo(f"Total: {total} providers discovered")
