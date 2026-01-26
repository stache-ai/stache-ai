"""Standard AI enrichers for Stache documents."""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext

from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

logger = logging.getLogger(__name__)

# Organization suggestion schema properties (added conditionally)
ORGANIZATION_SCHEMA_PROPERTIES = {
    "suggested_filename": {
        "type": "string",
        "pattern": "^[a-z0-9-]+$",
        "maxLength": 50,
        "description": "Short descriptive filename without extension (lowercase, hyphens only)"
    },
    "suggested_namespace": {
        "type": "string",
        "description": "Best matching namespace ID from the provided list, or 'default' if none fit"
    }
}

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
    Optionally suggests filename and namespace when _suggest_organization=True.
    Cost: ~$0.0005 per document (Nova Lite)
    """

    priority = 80  # Standard enrichment priority

    def get_schema(self) -> dict:
        """Return JSON schema, extended if organization suggestions requested."""
        schema = STANDARD_ENRICHMENT_SCHEMA.copy()

        # Check if organization suggestions requested (set in process())
        if getattr(self, "_suggest_organization", False):
            schema = {
                "type": "object",
                "properties": {
                    **STANDARD_ENRICHMENT_SCHEMA["properties"],
                    **ORGANIZATION_SCHEMA_PROPERTIES
                },
                "required": STANDARD_ENRICHMENT_SCHEMA["required"] + ["suggested_filename", "suggested_namespace"],
                "additionalProperties": False
            }

        return schema

    def build_prompt(self, content: str, metadata: dict) -> str:
        """Build prompt, including namespace list if organization suggestions requested."""
        filename = html.escape(metadata.get("filename", "unknown"))

        base_prompt = f"""Analyze this document and extract metadata.

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
   - Use "recursive" as fallback"""

        # Add organization suggestions if requested
        if getattr(self, "_suggest_organization", False):
            namespace_list = getattr(self, "_namespace_list", ["default"])
            namespace_str = ", ".join(namespace_list[:50])  # Limit to 50 namespaces

            base_prompt += f"""
4. suggested_filename: A short, descriptive filename based on content
   - Lowercase letters, numbers, and hyphens only
   - No file extension
   - Max 50 characters
   - Examples: "2024-tax-return", "project-proposal-acme", "meeting-notes-jan-15"
5. suggested_namespace: Best matching namespace from this list: [{namespace_str}]
   - Choose "default" if none of the namespaces fit well"""

        base_prompt += "\n\nBe concise and accurate. The summary will be used for semantic search."
        return base_prompt

    async def process(
        self,
        content: str,
        metadata: dict,
        context: "RequestContext"
    ) -> "EnrichmentResult":
        """Process with optional organization suggestions."""
        # Check if organization suggestions requested
        self._suggest_organization = metadata.get("_suggest_organization", False)

        if self._suggest_organization:
            # Fetch namespace list from provider
            namespace_provider = context.custom.get("namespace_provider")
            if namespace_provider:
                try:
                    namespaces = namespace_provider.list_namespaces()
                    self._namespace_list = [ns.get("id", ns.get("name", "default")) for ns in namespaces]
                except Exception as e:
                    logger.warning(f"Failed to fetch namespaces for suggestions: {e}")
                    self._namespace_list = ["default"]
            else:
                self._namespace_list = ["default"]

        # Call parent process (handles LLM call)
        return await super().process(content, metadata, context)

    def apply_enrichment(self, metadata: dict, llm_output: dict) -> dict:
        """Apply enrichment including optional organization suggestions."""
        metadata["ai_summary"] = llm_output["summary"]
        metadata["doc_type"] = llm_output["doc_type"]
        metadata["ai_chunking_strategy"] = llm_output["chunking_strategy"]

        # Handle organization suggestions
        apply_suggestions = metadata.get("_apply_suggestions", False)

        if "suggested_filename" in llm_output:
            if apply_suggestions:
                # Auto-apply: update filename directly
                original_filename = metadata.get("filename", "unknown")
                # Preserve file extension if present
                import os
                ext = os.path.splitext(original_filename)[1] if original_filename != "unknown" else ""
                metadata["filename"] = llm_output["suggested_filename"] + ext
                metadata["original_filename"] = original_filename  # Keep original for reference
            else:
                # Just store suggestion for user review
                metadata["suggested_filename"] = llm_output["suggested_filename"]

        if "suggested_namespace" in llm_output:
            if apply_suggestions:
                # Auto-apply: update namespace directly (will be used by pipeline)
                metadata["_suggested_namespace_to_apply"] = llm_output["suggested_namespace"]
            else:
                # Just store suggestion for user review
                metadata["suggested_namespace"] = llm_output["suggested_namespace"]

        # Mark as AI-enriched for tracking
        metadata["ai_enriched"] = True
        metadata["enrichment_version"] = "standard-0.1.1"

        # Clean up internal flags
        metadata.pop("_suggest_organization", None)
        metadata.pop("_apply_suggestions", None)

        return metadata
