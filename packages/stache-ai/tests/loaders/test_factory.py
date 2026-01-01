"""Tests for DocumentLoaderFactory"""

import tempfile
from pathlib import Path

import pytest

from stache_ai.loaders.base import DocumentLoader
from stache_ai.loaders.factory import DocumentLoaderFactory
from stache_ai.providers import plugin_loader


class MockLoader(DocumentLoader):
    """Mock loader for testing"""

    def __init__(self, extensions=None, priority=0, load_result="mock content"):
        self._extensions = extensions or ['mock']
        self._priority = priority
        self._load_result = load_result

    @property
    def extensions(self):
        return self._extensions

    def load(self, file_path: str) -> str:
        return self._load_result

    @property
    def priority(self):
        return self._priority


@pytest.fixture(autouse=True)
def reset_factory():
    """Reset factory state before each test"""
    DocumentLoaderFactory.reset()
    plugin_loader.reset()
    yield
    DocumentLoaderFactory.reset()
    plugin_loader.reset()


def test_discovers_loaders():
    """Test that factory discovers loaders from entry points"""
    loaders = plugin_loader.get_providers('loader')
    assert 'text' in loaders
    assert 'pdf' in loaders


def test_get_supported_extensions():
    """Test getting list of supported extensions"""
    extensions = DocumentLoaderFactory.get_supported_extensions()
    assert 'txt' in extensions
    assert 'md' in extensions
    assert 'pdf' in extensions


def test_get_loader_info():
    """Test getting loader diagnostic info"""
    info = DocumentLoaderFactory.get_loader_info()
    assert info['txt'] == 'TextLoader'
    assert info['md'] == 'TextLoader'
    # PDF loader varies based on optional packages installed
    # With stache-ai-ocr installed, OcrPdfLoader (priority 10) overrides PdfLoader (priority 0)
    assert info['pdf'] in ('PdfLoader', 'OcrPdfLoader')


def test_extension_aliasing():
    """Test that extension aliases are resolved correctly"""
    # markdown -> md
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Test")
        f.flush()
        md_path = f.name

    try:
        # Load with .markdown extension via filename parameter
        result = DocumentLoaderFactory.load_document(md_path, filename="test.markdown")
        assert result == "# Test"
    finally:
        Path(md_path).unlink()


def test_priority_handling():
    """Test that higher priority loaders override lower priority"""
    # Register a low-priority mock loader for txt
    low_priority = MockLoader(extensions=['txt'], priority=0, load_result="low")
    DocumentLoaderFactory.register(low_priority)

    # Register a high-priority mock loader for txt
    high_priority = MockLoader(extensions=['txt'], priority=10, load_result="high")
    DocumentLoaderFactory.register(high_priority)

    # High priority should win
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("test")
        f.flush()
        txt_path = f.name

    try:
        result = DocumentLoaderFactory.load_document(txt_path)
        assert result == "high"
    finally:
        Path(txt_path).unlink()


def test_priority_tie_first_discovered_wins():
    """Test that when priorities are equal, first-discovered wins"""
    # Both have priority 0
    first = MockLoader(extensions=['tie'], priority=0, load_result="first")
    second = MockLoader(extensions=['tie'], priority=0, load_result="second")

    DocumentLoaderFactory.register(first)
    DocumentLoaderFactory.register(second)

    # First should win
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tie', delete=False) as f:
        f.write("test")
        f.flush()
        tie_path = f.name

    try:
        result = DocumentLoaderFactory.load_document(tie_path)
        assert result == "first"
    finally:
        Path(tie_path).unlink()


def test_reset_clears_state():
    """Test that reset() clears factory state"""
    # Trigger discovery
    DocumentLoaderFactory.get_supported_extensions()
    assert DocumentLoaderFactory._discovered is True
    assert len(DocumentLoaderFactory._loaders) > 0

    # Reset
    DocumentLoaderFactory.reset()
    assert DocumentLoaderFactory._discovered is False
    assert len(DocumentLoaderFactory._loaders) == 0


def test_manual_register_works():
    """Test that manual registration works"""
    mock = MockLoader(extensions=['custom'], load_result="custom content")
    DocumentLoaderFactory.register(mock)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.custom', delete=False) as f:
        f.write("test")
        f.flush()
        custom_path = f.name

    try:
        result = DocumentLoaderFactory.load_document(custom_path)
        assert result == "custom content"
    finally:
        Path(custom_path).unlink()


def test_unknown_extension_raises_valueerror():
    """Test that unknown extension raises ValueError"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.unknown', delete=False) as f:
        f.write("test")
        f.flush()
        unknown_path = f.name

    try:
        with pytest.raises(ValueError) as exc_info:
            DocumentLoaderFactory.load_document(unknown_path)
        assert "No loader for extension: .unknown" in str(exc_info.value)
    finally:
        Path(unknown_path).unlink()


def test_load_text_file():
    """Test loading a text file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("Hello, world!")
        f.flush()
        txt_path = f.name

    try:
        result = DocumentLoaderFactory.load_document(txt_path)
        assert result == "Hello, world!"
    finally:
        Path(txt_path).unlink()


def test_load_markdown_file():
    """Test loading a markdown file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write("# Title\n\nContent")
        f.flush()
        md_path = f.name

    try:
        result = DocumentLoaderFactory.load_document(md_path)
        assert result == "# Title\n\nContent"
    finally:
        Path(md_path).unlink()


def test_backward_compat_function():
    """Test that the backward-compat load_document function works"""
    from stache_ai.loaders import load_document

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("Backward compat test")
        f.flush()
        txt_path = f.name

    try:
        result = load_document(txt_path)
        assert result == "Backward compat test"
    finally:
        Path(txt_path).unlink()
