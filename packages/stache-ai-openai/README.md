# stache-ai-openai

Openai provider for [Stache AI](https://github.com/stache-ai/stache-ai).

## Installation

```bash
pip install stache-ai-openai
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    llm_provider: "openai"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- openai>=1.0.0
