"""Base class for AI-powered enrichers with shared LLM integration."""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from ...middleware.context import RequestContext

from ...middleware.base import Enricher
from ...middleware.results import EnrichmentResult

logger = logging.getLogger(__name__)


class BaseAIEnricher(Enricher):
    """Base class for AI-powered enrichment middleware.

    Provides shared LLM integration and prompt building utilities.
    Not registered as entry point - library only.

    Subclasses must implement:
    - get_schema(): Return JSON schema for structured output
    - build_prompt(): Build prompt from content
    - apply_enrichment(): Apply extracted data to metadata
    """

    phase: ClassVar[str] = "enrich"
    priority: ClassVar[int] = 80  # After extract/transform, before late enrichers
    on_error: ClassVar[str] = "skip"  # Don't block ingestion on AI failures
    timeout_seconds: ClassVar[float | None] = 30.0

    def __init__(self, config):
        """Initialize with config for LLM access.

        Args:
            config: Settings instance with LLM provider configuration
        """
        self.config = config
        self._llm_provider = None
        self._provider_lock = threading.Lock()

    @property
    def llm_provider(self):
        """Lazy-load LLM provider from config (thread-safe)."""
        if self._llm_provider is None:
            with self._provider_lock:
                # Double-check after acquiring lock
                if self._llm_provider is None:
                    from ...providers import LLMProviderFactory
                    self._llm_provider = LLMProviderFactory.create(self.config)

                    # Verify structured output support
                    if "structured_output" not in self._llm_provider.capabilities:
                        raise RuntimeError(
                            f"LLM provider {self._llm_provider.get_name()} does not support "
                            "structured output. AI enrichment requires this capability."
                        )
        return self._llm_provider

    @abstractmethod
    def get_schema(self) -> dict:
        """Return JSON schema for structured output.

        Returns:
            JSON schema dict defining expected output structure
        """
        pass

    @abstractmethod
    def build_prompt(self, content: str, metadata: dict) -> str:
        """Build LLM prompt from content and metadata.

        Args:
            content: Document text content
            metadata: Current document metadata

        Returns:
            Formatted prompt string
        """
        pass

    @abstractmethod
    def apply_enrichment(self, metadata: dict, llm_output: dict) -> dict:
        """Apply LLM output to document metadata.

        Args:
            metadata: Current document metadata (will be modified)
            llm_output: Parsed JSON from LLM (matches get_schema())

        Returns:
            Updated metadata dict
        """
        pass

    def truncate_content(self, content: str, max_chars: int = 8000) -> str:
        """Truncate content to fit token budget.

        Args:
            content: Full document text
            max_chars: Maximum characters (rough token estimate: chars/4)

        Returns:
            Truncated content with marker if truncated
        """
        if len(content) <= max_chars:
            return content

        truncated = content[:max_chars]
        return truncated + "\n\n[... content truncated for analysis ...]"

    async def process(
        self,
        content: str,
        metadata: dict,
        context: RequestContext
    ) -> EnrichmentResult:
        """Process content with AI enrichment.

        Shared implementation: truncate, prompt, call LLM, apply results.
        """
        try:
            # Truncate content to token budget
            truncated_content = self.truncate_content(content)

            # Build prompt
            prompt = self.build_prompt(truncated_content, metadata)

            # Get schema
            schema = self.get_schema()

            # Call LLM in thread pool (sync method)
            llm_output = await asyncio.to_thread(
                self.llm_provider.generate_structured,
                prompt=prompt,
                schema=schema,
                max_tokens=self.config.ai_enrichment_max_tokens,
                temperature=self.config.ai_enrichment_temperature
            )

            # Apply enrichment to metadata
            enriched_metadata = self.apply_enrichment(metadata.copy(), llm_output)

            logger.info(
                f"{self.__class__.__name__} enriched document with fields: "
                f"{list(llm_output.keys())}"
            )

            return EnrichmentResult(
                action="transform",
                content=content,  # Content unchanged
                metadata=enriched_metadata
            )

        except NotImplementedError as e:
            # Provider doesn't support structured output
            logger.warning(
                f"{self.__class__.__name__} skipped: {e}"
            )
            return EnrichmentResult(action="allow")

        except Exception as e:
            # Log error but don't block ingestion
            logger.error(
                f"{self.__class__.__name__} failed: {e}",
                exc_info=True
            )
            return EnrichmentResult(action="allow")
