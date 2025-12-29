# stache-ai

A Python library for building AI-powered knowledge bases using Retrieval-Augmented Generation (RAG).

## Overview

stache-ai provides a pluggable framework for ingesting documents, storing embeddings, and executing semantic search with optional reranking. It includes support for multiple vector databases, LLM providers, embedding models, and document formats.

## Installation

Install the core package:

```bash
pip install stache-ai
```

## Quick Start

```python
from stache_ai.rag.pipeline import get_pipeline

# Get the pipeline (uses configured providers)
pipeline = get_pipeline()

# Ingest text
result = pipeline.ingest_text(
    text="Your knowledge base content here",
    metadata={"source": "example"}
)
print(f"Created {result['chunks_created']} chunks")

# Search
results = pipeline.query(
    question="What is this about?",
    top_k=5
)
for source in results['sources']:
    print(f"- {source['text'][:100]}...")
```

## Provider Packages

stache-ai uses a provider pattern to support different backends. Install optional provider packages to enable specific functionality:

### AWS Providers

```bash
pip install "stache-ai[aws]"
```

Includes:
- `stache-ai-s3vectors` - Amazon S3 Vectors for semantic search
- `stache-ai-dynamodb` - Amazon DynamoDB for namespace and document index storage
- `stache-ai-bedrock` - Amazon Bedrock for LLMs and embeddings

### Ollama

```bash
pip install "stache-ai[ollama]"
```

Includes:
- `stache-ai-ollama` - Ollama for local LLM and embedding models

### OpenAI

```bash
pip install "stache-ai[openai]"
```

Includes:
- `stache-ai-openai` - OpenAI for GPT models and embeddings

## Configuration

Configure stache-ai via environment variables or a `.env` file:

```bash
# Vector Database
VECTORDB_PROVIDER=s3vectors
VECTORDB_S3_REGION=us-east-1
VECTORDB_S3_INDEX_NAME=stache

# Embeddings
EMBEDDING_PROVIDER=bedrock
EMBEDDING_MODEL=cohere.embed-english-v3

# Namespaces
NAMESPACE_PROVIDER=dynamodb
NAMESPACE_DYNAMODB_TABLE=stache-namespaces

# LLM
LLM_PROVIDER=bedrock
LLM_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0

# Optional features
ENABLE_DOCUMENT_INDEX=true
EMBEDDING_AUTO_SPLIT_ENABLED=true
```

See `src/stache_ai/config.py` for all available options.

## Usage Examples

### Document Chunking

```python
from stache_ai.chunking import ChunkingStrategy

# Recursive character-level chunking
chunks = ChunkingStrategy.create(
    strategy="recursive",
    chunk_size=1024,
    chunk_overlap=100
).chunk("Your document text")

for chunk in chunks:
    print(chunk)
```

### Filtering Results

```python
# Search with metadata filter
results = pipeline.query(
    question="API documentation",
    filter={"source": "docs"}
)
```

### Namespace Isolation

```python
# Ingest to a specific namespace
pipeline.ingest_text(
    text="Project A data",
    namespace="project-a"
)

# Search within a namespace
results = pipeline.query(
    question="Find related content",
    namespace="project-a"
)
```

## API Server

Run a FastAPI server for HTTP access:

```bash
pip install stache-ai[dev]
python -m stache_ai.api.main
```

Server exposes endpoints for:
- `/api/query` - Semantic search
- `/api/capture` - Text ingestion
- `/api/namespaces` - Manage namespaces
- `/api/documents` - List and retrieve documents
- `/api/upload` - Upload files (PDF, DOCX, etc.)

## CLI Tools

### Admin CLI (stache-admin)

```bash
# Import documents from a directory
stache-import /path/to/documents --namespace my-docs

# List namespaces
stache-admin namespace-list

# View vector statistics
stache-admin vectors stats
```

### User CLI (stache-tools)

For search, ingest, and MCP server, install [stache-tools](https://github.com/stache-ai/stache-tools):

```bash
pip install stache-tools

# Search
stache search "your query"

# Ingest text
stache ingest -t "your text" -n namespace
```

## Testing

```bash
pip install stache-ai[dev]
pytest
```

## Documentation

- [GitHub Repository](https://github.com/stache-ai/stache-ai)
- [Architecture Guide](https://github.com/stache-ai/stache-ai/tree/main/docs)

## License

MIT
