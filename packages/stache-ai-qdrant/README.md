# stache-ai-qdrant

Qdrant provider for [Stache AI](https://github.com/stache-ai/stache).

## Installation

```bash
pip install stache-ai-qdrant
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache.config import Settings

settings = Settings(
    vectordb_provider: "qdrant"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- qdrant-client>=1.7.3
