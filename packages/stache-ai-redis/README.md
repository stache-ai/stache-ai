# stache-ai-redis

Redis provider for [Stache AI](https://github.com/stache-ai/stache-ai).

## Installation

```bash
pip install stache-ai-redis
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    namespace_provider: "redis"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- redis>=5.0.0
