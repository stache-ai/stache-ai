# Stache Plugin System

**Version**: 1.0
**Date**: 2025-12-22

## Overview

Stache uses Python's standard entry point mechanism for provider discovery. This allows both built-in and external providers to be registered declaratively via `pyproject.toml`, making the system fully extensible without modifying core code.

## Benefits

**For Users:**
- Install providers with pip
- Configure via environment variables
- No code changes needed

**For Developers:**
- Standard Python packaging
- Test plugins independently
- Distribute via PyPI

**For the Project:**
- External contributors don't touch core
- Lower maintenance burden
- Proprietary extensions possible

## Provider Types

Stache supports 6 provider types:

| Type | Entry Point Group | Purpose |
|------|------------------|---------|
| LLM | `stache.llm` | Language model providers (Claude, GPT, etc.) |
| Embeddings | `stache.embeddings` | Text embedding providers |
| VectorDB | `stache.vectordb` | Vector database providers |
| Namespace | `stache.namespace` | Namespace registry providers |
| Reranker | `stache.reranker` | Search result reranking |
| Document Index | `stache.document_index` | Document metadata storage |

## Architecture

```
pyproject.toml                      Entry Point Discovery
┌──────────────────────────┐       ┌───────────────────────────────┐
│ [project.entry-points]   │       │                               │
│ "stache.llm"             │──────►│ importlib.metadata.entry_    │
│   anthropic = "..."      │       │ points().select(group=...)    │
│   bedrock = "..."        │       │                               │
│                          │       │         │                     │
│ "stache.embeddings"      │       │         ▼                     │
│   bedrock = "..."        │       │ ep.load() → ProviderClass    │
│   ...                    │       │                               │
└──────────────────────────┘       └───────────────────────────────┘
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Plugin Loader                              │
│  Caches providers by type for fast access                        │
└──────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Factories                                 │
│  LLMProviderFactory.create(settings) → provider instance          │
└──────────────────────────────────────────────────────────────────┘
```

## Creating an External Plugin

### Quick Start

Create a new package that provides a custom provider:

```bash
mkdir stache-milvus
cd stache-milvus
```

### Directory Structure

```
stache-milvus/
├── pyproject.toml          # Package metadata and entry points
├── README.md               # Usage instructions
├── LICENSE                 # License file
└── stache_milvus/           # Package code (note: underscore)
    ├── __init__.py
    └── provider.py         # Your provider implementation
```

### Step 1: Implement the Provider

Create `stache_milvus/provider.py`:

```python
"""Milvus vector database provider for Stache"""

from typing import List, Dict, Any, Optional, Set
from stache.providers.base import VectorDBProvider
from stache.config import Settings


class MilvusVectorDBProvider(VectorDBProvider):
    """Milvus-based vector database provider

    Combines high-performance with vector similarity search.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        # Initialize your provider here
        from milvus import connections
        self.driver = connections.driver(
            settings.milvus_uri,
            auth=(settings.milvus_user, settings.milvus_password)
        )

    @property
    def capabilities(self) -> Set[str]:
        """Declare provider capabilities"""
        return {
            "vector_search",
            "metadata_filter",
            "batch_insert",
        }

    def insert(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ) -> List[str]:
        """Insert vectors into Milvus"""
        # Your implementation here
        pass

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors"""
        # Your implementation here
        pass

    def delete(
        self,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> int:
        """Delete vectors"""
        # Your implementation here
        pass

    def count(self, namespace: Optional[str] = None) -> int:
        """Count vectors in namespace"""
        # Your implementation here
        pass
```

### Configuration

Plugin providers access configuration through the Settings object. Stache uses pydantic-settings, which reads environment variables automatically:

```bash
export MILVUS_URI=localhost
export MILVUS_USER=milvus
export MILVUS_PASSWORD=secret
```

Your provider gets these via `settings.milvus_uri`, `settings.milvus_user`, etc. The Settings model reads `MILVUS_*` variables when you reference them.

You can extend the Settings model in your package for type safety, but it's not required.

### Step 2: Configure Entry Point

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "stache-milvus"
version = "0.1.0"
description = "Milvus vector database provider for Stache"
requires-python = ">=3.10"
dependencies = [
    "stache>=0.1.0",
    "milvus>=5.0.0",
]

# Entry point registration
[project.entry-points."stache.vectordb"]
milvus = "stache_milvus.provider:MilvusVectorDBProvider"
```

Format: `name = "package.module:ClassName"`

### Step 3: Test Your Plugin

```bash
# Install in development mode
pip install -e .

# Verify entry point is registered
python -c "import importlib.metadata; eps = list(importlib.metadata.entry_points().select(group='stache.vectordb')); print([ep.name for ep in eps])"

# Should see: ['qdrant', 'pinecone', 'chroma', 's3vectors', 'milvus']
```

### Step 4: Use Your Plugin

```bash
# Set environment variables
export VECTORDB_PROVIDER=milvus
export MILVUS_URI=localhost
export MILVUS_USER=milvus
export MILVUS_PASSWORD=secret

# Run your app
python your_app.py
```

## Testing Your Plugin

### Unit Tests

Test your provider in isolation:

```python
import pytest
from stache.config import Settings
from stache_milvus.provider import MilvusVectorDBProvider


def test_provider_initialization():
    settings = Settings(
        milvus_uri="localhost",
        milvus_user="test",
        milvus_password="test"
    )
    provider = MilvusVectorDBProvider(settings)
    assert provider is not None
    assert "vector_search" in provider.capabilities


def test_provider_insert():
    settings = Settings(...)
    provider = MilvusVectorDBProvider(settings)

    vectors = [[0.1, 0.2, 0.3]]
    texts = ["test document"]

    ids = provider.insert(vectors, texts)
    assert len(ids) == 1
```

### Integration Tests

Test that Stache discovers your plugin:

```python
from stache.providers import VectorDBProviderFactory


def test_provider_discovered():
    available = VectorDBProviderFactory.get_available_providers()
    assert 'milvus' in available


def test_provider_can_be_created():
    settings = Settings(vectordb_provider='milvus', ...)
    provider = VectorDBProviderFactory.create(settings)
    assert provider.__class__.__name__ == 'MilvusVectorDBProvider'
```

## Publishing Your Plugin

### To PyPI

```bash
pip install build twine
python -m build
twine upload dist/*

# Users install with:
pip install stache-milvus
```

### To Private Package Index

```bash
twine upload --repository-url https://your-pypi.example.com dist/*

# Users install with:
pip install --index-url https://your-pypi.example.com stache-milvus
```

### Direct Distribution

```bash
python -m build

# Share the wheel file
# Install with:
pip install stache_milvus-0.1.0-py3-none-any.whl
```

## Provider Base Classes Reference

### VectorDBProvider

Required:
- `insert()` - Add vectors
- `search()` - Find similar vectors
- `delete()` - Remove vectors
- `count()` - Count vectors

Optional:
- `capabilities` property

### LLMProvider

Required:
- `generate()` - Text completion

### EmbeddingProvider

Required:
- `embed()` - Convert text to vector
- `embed_batch()` - Convert multiple texts

### NamespaceProvider

Required:
- `create_namespace()`
- `delete_namespace()`
- `list_namespaces()`
- `get_namespace()`

### DocumentIndexProvider

Required:
- `index_document()`
- `get_document()`
- `list_documents()`
- `delete_document()`

### RerankerProvider

Required:
- `rerank()` - Reorder results

## Troubleshooting

### Plugin Not Discovered

**Problem**: `Unknown vectordb provider: milvus`

**Solutions**:
1. Verify entry point is registered:
   ```bash
   python -c "import importlib.metadata; print(list(importlib.metadata.entry_points().select(group='stache.vectordb')))"
   ```

2. Reinstall in editable mode:
   ```bash
   pip install -e . --force-reinstall
   ```

3. Check for typos in entry point path

### Import Errors

**Problem**: `ImportError: cannot import name 'MilvusVectorDBProvider'`

**Solutions**:
1. Verify module path is correct
2. Check class name matches entry point
3. Ensure package is installed: `pip list | grep stache-milvus`

### Missing Dependencies

**Problem**: Plugin discovered but fails to load

**Solutions**:
1. Check dependencies in pyproject.toml
2. Install optional dependencies
3. Plugin loader silently skips providers with missing deps

## Examples

See built-in providers in `stache/providers/` for production examples.
