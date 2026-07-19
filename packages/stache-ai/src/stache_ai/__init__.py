"""Stache - Your personal AI-powered knowledge base"""

try:
    from importlib.metadata import version
    __version__ = version("stache-ai")
except Exception:
    __version__ = "0.3.1"  # Fallback for development