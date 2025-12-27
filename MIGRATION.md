# Migration Guide: RAGBrain → Stache

RAGBrain has been renamed to **Stache** (stache-ai on GitHub/PyPI).

## For Existing Users

### Update Installation

```bash
# Uninstall old package
pip uninstall ragbrain

# Install new package
pip install stache-ai
```

### Update Imports

```python
# Old
from ragbrain.rag import Pipeline
import ragbrain.config

# New
from stache.rag import Pipeline
import stache.config
```

### Update CLI Commands

```bash
# Old
ragbrain-import ./docs
ragbrain namespace list

# New
stache-import ./docs
stache namespace list
```

### Update Environment Variables

- `QDRANT_COLLECTION=ragbrain` → `QDRANT_COLLECTION=stache`
- `MONGODB_DATABASE=ragbrain` → `MONGODB_DATABASE=stache`

### Docker Compose

```bash
# Old containers
ragbrain-app
ragbrain-vectordb
ragbrain-mongodb

# New containers
stache-app
stache-vectordb
stache-mongodb
```

### Docker Volumes

Existing Docker volumes will continue to work:
- `qdrant_storage` volume remains accessible
- `mongodb_data` volume remains accessible
- No local data migration needed

## For Plugin Developers

External packages with entry points must update:

```toml
# Old
[project.entry-points."ragbrain.llm"]

# New
[project.entry-points."stache.llm"]
```

## Why the Rename?

Better branding and clearer identity as we approach v1.0.
