"""Post-ingest processors for artifact generation.

PostIngestProcessors run after chunks are stored to generate additional
artifacts like summaries, extracted entities, or metadata enrichments.
"""

from .summary import HeuristicSummaryGenerator

__all__ = ["HeuristicSummaryGenerator"]
