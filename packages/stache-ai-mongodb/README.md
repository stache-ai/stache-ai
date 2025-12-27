# stache-ai-mongodb

Mongodb provider for [Stache AI](https://github.com/stache-ai/stache).

## Installation

```bash
pip install stache-ai-mongodb
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache.config import Settings

settings = Settings(
    namespace_provider: "mongodb"
)
```

The provider will be automatically discovered via entry points.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- pymongo>=4.6.0
