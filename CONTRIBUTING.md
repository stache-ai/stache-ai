# Contributing

## Setup

```bash
# Clone and setup
git clone https://github.com/stache-ai/stache-ai.git
cd stache/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy env and add API keys
cp .env.example .env

# Start Qdrant
docker run -p 6333:6333 qdrant/qdrant

# Run backend
uvicorn stache.api.main:app --reload --port 8000
```

## Plugin Development Setup

Stache uses Python entry points for provider discovery. Install the package in editable mode for development:

```bash
git clone https://github.com/yourusername/stache
cd stache/backend

# Install in editable mode
pip install -e .

# Verify providers are registered
python -c "import importlib.metadata; eps = list(importlib.metadata.entry_points().select(group='stache.llm')); print(f'Found {len(eps)} LLM providers')"

# Run tests
pytest
```

Without `pip install -e .`, providers won't be discovered and tests will fail.

### After Modifying Entry Points

If you change `pyproject.toml` entry points, reinstall:

```bash
pip install -e . --force-reinstall --no-deps
```

### Verify Entry Points

Check all registered providers:

```bash
python << 'EOF'
import importlib.metadata

for group in ['stache.llm', 'stache.embeddings', 'stache.vectordb',
              'stache.namespace', 'stache.reranker', 'stache.document_index']:
    eps = list(importlib.metadata.entry_points().select(group=group))
    print(f"{group}: {[ep.name for ep in eps]}")
EOF
```

## Tests

```bash
cd backend
pytest                                    # all tests
pytest --cov=stache --cov-report=html   # with coverage
pytest tests/test_chunking.py -v          # specific file
```

## Adding Providers

Providers are registered via entry points in `pyproject.toml`. No manual registration needed.

### Built-in Provider

Add your provider to the codebase:

```python
# backend/stache/providers/embeddings/your_provider.py
from stache.providers.base import EmbeddingProvider

class YourEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings):
        self.settings = settings

    def embed(self, text: str) -> List[float]:
        # Your implementation
        pass

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # Your implementation
        pass

    def get_dimensions(self) -> int:
        return 1024
```

Register it in `backend/pyproject.toml`:

```toml
[project.entry-points."stache.embeddings"]
your_provider = "stache.providers.embeddings.your_provider:YourEmbeddingProvider"
```

Reinstall to register:

```bash
pip install -e . --force-reinstall --no-deps
```

### External Plugin

For third-party providers, see [docs/plugins.md](docs/plugins.md) for the complete guide on creating and distributing external plugins.
