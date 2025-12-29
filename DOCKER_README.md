# Stache

**Storage for AI** - A production-ready RAG (Retrieval-Augmented Generation) system that gives AI persistent memory and knowledge retrieval.

## Quick Start

```bash
# Pull the image
docker pull stacheai/stache-ai:latest

# Run with docker-compose (recommended)
curl -O https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/stache-ai/stache-ai/main/.env.example
cp .env.example .env
# Edit .env with your API keys
docker-compose up -d

# Open the UI
open http://localhost:8000
```

## Tags

| Tag | OCR Support | Size | Description |
|-----|-------------|------|-------------|
| `latest`, `0.1.0` | Yes | ~715MB | Full featured with OCR for scanned PDFs |
| `slim`, `0.1.0-slim` | No | ~485MB | Smaller image, text-based documents only |

## Features

- **Semantic Search** - Find documents by meaning, not just keywords
- **Document Import** - PDF, EPUB, Markdown, DOCX, PPTX, VTT/SRT
- **AI Answers** - Ask questions, get synthesized answers
- **OCR Support** - Extract text from scanned PDFs (full image only)
- **Multiple Providers** - OpenAI, Anthropic, Ollama, AWS Bedrock
- **Vector Databases** - Qdrant, Pinecone, S3 Vectors, Redis

## Environment Variables

Required:
```bash
OPENAI_API_KEY=sk-...        # or
ANTHROPIC_API_KEY=sk-ant-... # at least one LLM provider
```

Optional:
```bash
# Providers
LLM_PROVIDER=openai          # openai, anthropic, ollama, bedrock
EMBEDDING_PROVIDER=openai    # openai, ollama, bedrock, cohere
VECTORDB_PROVIDER=qdrant     # qdrant, pinecone, s3vectors, redis

# Qdrant (default vector DB)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=stache

# Ollama (local models)
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2
```

## Volumes

```yaml
volumes:
  - ./data/uploads:/app/uploads    # Uploaded files
  - ./data:/app/data               # SQLite namespace DB
```

## Ports

| Port | Service |
|------|---------|
| 8000 | Web UI + API |

## Health Check

```bash
curl http://localhost:8000/health
```

## Documentation

- [GitHub Repository](https://github.com/stache-ai/stache-ai)
- [Full Documentation](https://github.com/stache-ai/stache-ai#readme)
- [Provider Setup](https://github.com/stache-ai/stache-ai/blob/main/docs/plugins.md)

## License

MIT License
