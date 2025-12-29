# stache-ai-anthropic

Anthropic provider for [Stache AI](https://github.com/stache-ai/stache-ai).

## Installation

```bash
pip install stache-ai-anthropic
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    llm_provider: "anthropic"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- anthropic>=0.18.0
