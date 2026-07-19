"""Standard AI enrichment plugin for Stache."""

from .enrichers import SummaryEnricher

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-enrichment")
except Exception:
    __version__ = "0.1.1"  # Fallback for development
__all__ = ["SummaryEnricher"]
