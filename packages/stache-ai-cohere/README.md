# stache-ai-cohere

Cohere provider for [Stache AI](https://github.com/stache-ai/stache-ai).

## Installation

```bash
pip install stache-ai-cohere
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    embeddings_provider: "cohere"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- cohere>=4.0.0
