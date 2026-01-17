"""Standard AI enrichers for Stache documents."""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext

from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

logger = logging.getLogger(__name__)

# JSON schema for standard enrichment
STANDARD_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "minLength": 20,
            "maxLength": 300,
            "description": "2-3 sentence summary of document content and purpose"
        },
        "doc_type": {
            "type": "string",
            "enum": [
                "article", "guide", "tutorial", "reference", "api_docs",
                "meeting_notes", "email", "report", "proposal", "specification",
                "blog_post", "research_paper", "presentation", "legal", "code",
                "changelog", "readme", "other"
            ],
            "description": "Document type classification"
        },
        "chunking_strategy": {
            "type": "string",
            "enum": ["recursive", "markdown", "hierarchical", "semantic"],
            "description": "Recommended chunking strategy based on document structure"
        }
    },
    "required": ["summary", "doc_type", "chunking_strategy"],
    "additionalProperties": False
}


class SummaryEnricher(BaseAIEnricher):
    """AI-powered enrichment: summary, doc_type, chunking_strategy.

    Generates basic metadata for improved search and organization.
    Cost: ~$0.0005 per document (Nova Lite)
    """

    priority = 80  # Standard enrichment priority

    def get_schema(self) -> dict:
        """Return JSON schema for standard enrichment."""
        return STANDARD_ENRICHMENT_SCHEMA

    def build_prompt(self, content: str, metadata: dict) -> str:
        """Build prompt for standard enrichment."""
        filename = html.escape(metadata.get("filename", "unknown"))

        return f"""Analyze this document and extract metadata.

<document filename="{filename}">
{content}
</document>

Extract:
1. summary: 2-3 sentence summary (what is this document about?)
2. doc_type: Choose the best classification from the schema
3. chunking_strategy:
   - Use "markdown" for markdown files with headers
   - Use "hierarchical" for structured documents (PDFs, DOCX with sections)
   - Use "semantic" for narrative text (articles, essays)
   - Use "recursive" as fallback

Be concise and accurate. The summary will be used for semantic search."""

    def apply_enrichment(self, metadata: dict, llm_output: dict) -> dict:
        """Apply standard enrichment to metadata."""
        metadata["ai_summary"] = llm_output["summary"]
        metadata["doc_type"] = llm_output["doc_type"]
        metadata["ai_chunking_strategy"] = llm_output["chunking_strategy"]

        # Mark as AI-enriched for tracking
        metadata["ai_enriched"] = True
        metadata["enrichment_version"] = "standard-0.1.0"

        return metadata
