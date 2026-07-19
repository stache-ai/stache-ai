"""Document format loaders for Stache AI"""

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-documents")
except Exception:
    __version__ = "0.1.1"  # Fallback for development