# Stache

**Storage for AI** - A production-ready RAG (Retrieval-Augmented Generation) system that gives AI persistent memory and knowledge retrieval.

## Quick Start

### Option 1: Clone the Repository (Recommended)

```bash
git clone https://github.com/stache-ai/stache-ai.git
cd stache
```

Then choose your embedding provider:

**Local Ollama (no API keys needed):**
```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

**OpenAI API:**
```bash
echo "OPENAI_API_KEY=sk-..." > .env
docker compose -f docker-compose.yml -f docker-compose.openai.yml up -d
```

### Option 2: Download Files Only

#### Local Ollama (no API keys)

**Linux/macOS:**
```bash
mkdir stache && cd stache
curl -O https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.local.yml
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

**Windows (PowerShell):**
```powershell
mkdir stache; cd stache
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.yml" -OutFile "docker-compose.yml"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.local.yml" -OutFile "docker-compose.local.yml"
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

#### OpenAI API

**Linux/macOS:**
```bash
mkdir stache && cd stache
curl -O https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.openai.yml
echo "OPENAI_API_KEY=sk-..." > .env
docker compose -f docker-compose.yml -f docker-compose.openai.yml up -d
```

**Windows (PowerShell):**
```powershell
mkdir stache; cd stache
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.yml" -OutFile "docker-compose.yml"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/stache-ai/stache-ai/main/docker-compose.openai.yml" -OutFile "docker-compose.openai.yml"
"OPENAI_API_KEY=sk-..." | Out-File -Encoding utf8 .env
docker compose -f docker-compose.yml -f docker-compose.openai.yml up -d
```

### Verify

```bash
curl http://localhost:8000/api/health
# Or open http://localhost:8000 in your browser
```

## Tags

| Tag | OCR Support | Size | Description |
|-----|-------------|------|-------------|
| `latest`, `0.1.2` | Yes | ~715MB | Full featured with OCR for scanned PDFs |
| `slim`, `0.1.2-slim` | No | ~485MB | Smaller image, text-based documents only |

## Features

- **Semantic Search** - Find documents by meaning, not just keywords
- **Document Import** - PDF, EPUB, Markdown, DOCX, PPTX, VTT/SRT
- **AI Answers** - Ask questions, get synthesized answers
- **OCR Support** - Extract text from scanned PDFs (full image only)
- **Multiple Providers** - OpenAI, Anthropic, Ollama, AWS Bedrock
- **Vector Databases** - Qdrant, Pinecone, S3 Vectors, Redis

## Environment Variables

**For OpenAI:**
```bash
OPENAI_API_KEY=sk-...
```

**For Local Ollama (no API keys):**
```bash
# Use docker-compose.local.yml - no environment variables needed
# Default embedding model: nomic-embed-text (768 dims)
```

**Optional Settings:**
```bash
# Embedding model (for Ollama)
OLLAMA_EMBEDDING_MODEL=nomic-embed-text  # or mxbai-embed-large
EMBEDDING_DIMENSION=768                   # or 1024 for mxbai-embed-large

# Document storage
DOCUMENT_INDEX_PROVIDER=mongodb           # Required for local setup
```

## Volumes

```yaml
volumes:
  - ./data/uploads:/app/uploads    # Uploaded files
  - ./data:/app/data               # Application data
  - ./data/qdrant:/qdrant/storage  # Vector database
  - ./data/mongodb:/data/db        # Document metadata
  - ./data/ollama:/root/.ollama    # Ollama models (local only)
```

## Ports

| Port | Service |
|------|---------|
| 8000 | Web UI + API |
| 6333 | Qdrant (vector DB) |
| 11434 | Ollama (local only) |
| 27017 | MongoDB |

## Documentation

- [GitHub Repository](https://github.com/stache-ai/stache-ai)
- [Full Documentation](https://github.com/stache-ai/stache-ai#readme)
- [stache-tools (CLI + MCP)](https://github.com/stache-ai/stache-tools)

## License

MIT License
