# stache-ai-ollama

Ollama provider for [Stache AI](https://github.com/stache-ai/stache-ai).

## Installation

```bash
pip install stache-ai-ollama
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    llm_provider: "ollama"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- httpx>=0.25.0
