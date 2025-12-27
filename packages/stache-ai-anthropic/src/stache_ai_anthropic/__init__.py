"""stache-ai-anthropic - Anthropic provider for Stache AI

This package provides anthropic integration for Stache.
Install and the provider will be automatically discovered via entry points.

Usage:
    # Just install the package
    pip install stache-ai-anthropic

    # Configure in your .env or settings
    # (provider name matches entry point name)
"""

from .provider import AnthropicLLMProvider

__version__ = "0.1.0"
__all__ = ["AnthropicLLMProvider"]
