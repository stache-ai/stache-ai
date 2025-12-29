"""Resilience utilities for embedding operations.

This module provides automatic splitting capabilities for handling oversized
text chunks that exceed embedding provider token limits.

## Architecture

Auto-splitting is implemented as a **wrapper pattern** that works with ANY
embedding provider. When an embedding operation fails with a context-length
error, the wrapper automatically splits the text and retries each half
recursively until successful or max depth is reached.

This is provider-agnostic resilience logic that belongs at the orchestration
layer, following the same pattern as the HTTP resilience utilities.

## Usage

### Basic Usage (Pipeline Integration)

The wrapper is automatically used by Pipeline when `embedding_auto_split_enabled=True`:

```python
# In config or environment
EMBEDDING_AUTO_SPLIT_ENABLED=true
EMBEDDING_AUTO_SPLIT_MAX_DEPTH=4

# Pipeline automatically wraps provider
result = pipeline.ingest_text(text="very long text...", namespace="test")

# Result includes split info
print(result["splits_created"])  # Number of chunks that were split
print(result["info"])  # ["2 chunk(s) were auto-split due to..."]
```

### Direct Usage (Advanced)

You can also use the wrapper directly:

```python
from stache_ai.rag.embedding_resilience import (
    AutoSplitEmbeddingWrapper,
    OllamaErrorClassifier
)
from stache_ai.providers.factories import EmbeddingProviderFactory

# Create base provider
base_provider = EmbeddingProviderFactory.create(settings)

# Wrap with auto-split
wrapper = AutoSplitEmbeddingWrapper(
    provider=base_provider,
    max_split_depth=4,
    error_classifier=OllamaErrorClassifier(),
    enabled=True
)

# Use wrapper instead of provider
results, split_count = wrapper.embed_batch_with_splits(texts)

for result in results:
    if result.was_split:
        print(f"Split {result.split_index + 1}/{result.split_total}")
```

## Error Classification

Different providers have different error formats. Use provider-specific
classifiers for best results:

- **DefaultErrorClassifier**: Conservative pattern matching (default)
- **OllamaErrorClassifier**: Ollama-specific patterns
- **BedrockErrorClassifier**: Bedrock structured error responses

## Split Metadata

Split chunks include metadata markers for tracking:

- `_split`: True if chunk was produced by auto-splitting
- `_split_index`: Position in split sequence (0-based)
- `_split_total`: Total number of splits from original
- `_parent_chunk_index`: Original chunk index before splitting

## Configuration

```python
# Enable/disable auto-split
embedding_auto_split_enabled: bool = True

# Maximum recursion depth (4 = up to 16 sub-chunks)
embedding_auto_split_max_depth: int = 4  # Range: 1-10
```

## Testing

See tests/rag/test_embedding_resilience.py for comprehensive examples.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """Result of embedding operation with split metadata.

    Attributes:
        text: The text that was embedded
        embedding: The embedding vector
        was_split: Whether this text was produced by auto-splitting
        split_index: Position in split sequence (0-based)
        split_total: Total number of splits from original text
        parent_index: Original chunk index before splitting (if split)
    """
    text: str
    embedding: list[float]
    was_split: bool = False
    split_index: int = 0
    split_total: int = 1
    parent_index: int | None = None


class ErrorClassifier(Protocol):
    """Protocol for error classification strategies."""

    def is_context_length_error(self, error: Exception) -> bool:
        """Return True if error indicates context length exceeded."""
        ...


class TextSplitter:
    """Utilities for intelligent text splitting at natural boundaries."""

    @staticmethod
    def find_split_point(text: str) -> int:
        """
        Find optimal point to split text, preferring natural boundaries.

        Priority order:
        1. Paragraph breaks (\\n\\n)
        2. Sentence ends (. ! ?)
        3. Word boundaries (spaces)
        4. Character midpoint (fallback)

        Args:
            text: Text to split

        Returns:
            Character index for split point
        """
        mid = len(text) // 2

        # Look for paragraph break near middle (±200 chars)
        for delta in range(0, min(200, mid), 10):
            for pos in [mid - delta, mid + delta]:
                if 0 < pos < len(text) - 1:
                    if text[pos:pos+2] == '\n\n':
                        return pos + 2

        # Look for sentence end near middle (±200 chars)
        for delta in range(0, min(200, mid), 10):
            for pos in [mid - delta, mid + delta]:
                if 0 < pos < len(text) - 1:
                    if text[pos-1:pos+1] in ['. ', '! ', '? ']:
                        return pos + 1

        # Fall back to word boundary (±100 chars)
        space_pos = text.rfind(' ', mid - 100, mid + 100)
        if space_pos > 0:
            return space_pos + 1

        # Last resort: exact middle
        return mid


class DefaultErrorClassifier:
    """Conservative default error classifier.

    Uses pattern matching on error messages. More conservative than
    provider-specific classifiers to avoid false positives.
    """

    def is_context_length_error(self, error: Exception) -> bool:
        """Check if error indicates context length exceeded.

        Looks for common patterns across providers:
        - "context length"
        - "token limit"
        - "maximum context"
        - "too many tokens"
        - "prompt is too long"

        Args:
            error: Exception from embedding operation

        Returns:
            True if error appears to be context-length related
        """
        error_str = str(error).lower()

        # Explicit context length patterns
        patterns = [
            'context length',
            'token limit',
            'maximum context',
            'too many tokens',
            'prompt is too long',
            'input is too long',
            'exceeds maximum',
        ]

        return any(pattern in error_str for pattern in patterns)


class OllamaErrorClassifier(DefaultErrorClassifier):
    """Ollama-specific error classifier.

    Ollama sometimes returns HTTP 500 with "context length" in message.
    This classifier is more aggressive for Ollama-specific patterns.
    """

    def is_context_length_error(self, error: Exception) -> bool:
        # Try parent classifier first
        if super().is_context_length_error(error):
            return True

        error_str = str(error).lower()

        # Ollama-specific: Check for "prompt is too long" in 500 errors
        if 'prompt is too long' in error_str:
            return True

        # Conservative: Only trigger on 500 if we see explicit context message
        if '500' in error_str and 'context' in error_str:
            return True

        return False


class BedrockErrorClassifier(DefaultErrorClassifier):
    """Bedrock-specific error classifier.

    Bedrock returns structured errors with specific codes.
    """

    def is_context_length_error(self, error: Exception) -> bool:
        # Check for structured error response
        if hasattr(error, 'response'):
            error_code = error.response.get('Error', {}).get('Code', '')
            # Bedrock validation errors for token limits
            if error_code in ['ValidationException', 'ThrottlingException']:
                message = error.response.get('Error', {}).get('Message', '').lower()
                if any(p in message for p in ['token', 'length', 'context']):
                    return True

        # Fall back to string matching
        return super().is_context_length_error(error)


class AutoSplitEmbeddingWrapper:
    """
    Wraps any EmbeddingProvider with auto-split resilience.

    When an embedding operation fails with a context-length error,
    automatically splits the text and retries each half recursively.

    This is provider-agnostic - it works with Ollama, Bedrock, Mixedbread,
    or any other EmbeddingProvider implementation.

    Example:
        >>> from stache_ai.providers.factories import EmbeddingProviderFactory
        >>> base_provider = EmbeddingProviderFactory.create(settings)
        >>> wrapper = AutoSplitEmbeddingWrapper(
        ...     provider=base_provider,
        ...     max_split_depth=4,
        ...     error_classifier=OllamaErrorClassifier()
        ... )
        >>> results, split_count = wrapper.embed_batch_with_splits(texts)
    """

    def __init__(
        self,
        provider,  # EmbeddingProvider (avoid circular import)
        max_split_depth: int = 4,
        error_classifier: ErrorClassifier | None = None,
        enabled: bool = True
    ):
        """
        Initialize auto-split wrapper.

        Args:
            provider: Base embedding provider to wrap
            max_split_depth: Maximum recursion depth (4 = up to 16 sub-chunks)
            error_classifier: Strategy for detecting context errors (default: DefaultErrorClassifier)
            enabled: Whether auto-split is enabled (disable for testing)
        """
        self.provider = provider
        self.max_split_depth = max_split_depth
        self.error_classifier = error_classifier or DefaultErrorClassifier()
        self.enabled = enabled
        self._splitter = TextSplitter()

    def _embed_single_with_auto_split(
        self,
        text: str,
        original_index: int,
        depth: int = 0
    ) -> list[EmbeddingResult]:
        """
        Embed single text with automatic splitting on error.

        Recursively splits text until it fits within provider's token limit
        or max_split_depth is reached.

        Args:
            text: Text to embed
            original_index: Index of original chunk (before any splitting)
            depth: Current recursion depth (for max depth checking)

        Returns:
            List of EmbeddingResult (1 if no split, 2+ if split occurred)

        Raises:
            Exception: Re-raises if error is not context-length related,
                      or if max_split_depth is exceeded
        """
        try:
            # Call provider's normal embed method
            embedding = self.provider.embed(text)

            return [EmbeddingResult(
                text=text,
                embedding=embedding,
                was_split=False,
                split_index=0,
                split_total=1,
                parent_index=original_index
            )]

        except Exception as e:
            # Check if this is a context-length error AND we can still split
            is_context_error = self.error_classifier.is_context_length_error(e)
            can_split = depth < self.max_split_depth

            if not self.enabled or not is_context_error or not can_split:
                # Re-raise if:
                # - Auto-split disabled
                # - Not a context error
                # - Max depth exceeded
                logger.debug(
                    f"Not auto-splitting: enabled={self.enabled}, "
                    f"is_context_error={is_context_error}, "
                    f"can_split={can_split} (depth={depth}/{self.max_split_depth})"
                )
                raise

            # Auto-split and retry
            logger.info(
                f"Context length error detected, splitting text "
                f"({len(text)} chars) at depth {depth}/{self.max_split_depth}"
            )

            # Find optimal split point
            split_point = self._splitter.find_split_point(text)
            left_text = text[:split_point].strip()
            right_text = text[split_point:].strip()

            logger.debug(
                f"Split into left ({len(left_text)} chars) and "
                f"right ({len(right_text)} chars)"
            )

            # Recursively embed each half
            left_results = self._embed_single_with_auto_split(
                left_text, original_index, depth + 1
            )
            right_results = self._embed_single_with_auto_split(
                right_text, original_index, depth + 1
            )

            # Combine and annotate with split metadata
            all_results = left_results + right_results
            for i, result in enumerate(all_results):
                result.was_split = True
                result.split_index = i
                result.split_total = len(all_results)
                result.parent_index = original_index

            logger.info(
                f"Successfully split into {len(all_results)} sub-chunks "
                f"at depth {depth}"
            )

            return all_results

    def embed_batch_with_splits(
        self,
        texts: list[str]
    ) -> tuple[list[EmbeddingResult], int]:
        """
        Embed batch of texts with automatic splitting.

        This is the main entry point for pipeline integration.

        Args:
            texts: List of text chunks to embed

        Returns:
            Tuple of (results, split_count) where:
            - results: List of EmbeddingResult (may be longer than input if splits occurred)
            - split_count: Number of original chunks that required splitting

        Example:
            >>> results, split_count = wrapper.embed_batch_with_splits(["short", "very long text..."])
            >>> print(f"Created {len(results)} embeddings from {len(texts)} inputs")
            >>> print(f"{split_count} chunks were auto-split")
        """
        all_results = []
        split_count = 0

        for i, text in enumerate(texts):
            results = self._embed_single_with_auto_split(text, original_index=i)

            # Track how many original chunks were split
            if len(results) > 1:
                split_count += 1

            all_results.extend(results)

        logger.info(
            f"Embedded {len(texts)} chunks → {len(all_results)} results "
            f"({split_count} splits)"
        )

        return all_results, split_count

    # Delegate other methods to base provider
    def get_name(self) -> str:
        return f"AutoSplit({self.provider.get_name()})"

    def get_dimensions(self) -> int:
        return self.provider.get_dimensions()

    def is_available(self) -> bool:
        return self.provider.is_available()
