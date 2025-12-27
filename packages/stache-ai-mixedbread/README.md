# stache-ai-mixedbread

Mixedbread provider for [Stache AI](https://github.com/stache-ai/stache).

## Installation

```bash
pip install stache-ai-mixedbread
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache.config import Settings

settings = Settings(
    embeddings_provider: "mixedbread"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- httpx>=0.25.0
