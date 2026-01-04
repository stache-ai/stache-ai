# Stache 🥸

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**Curated Storage for AI** - A production-ready infrastructure layer that gives AI systems persistent memory and knowledge retrieval through RAG (Retrieval-Augmented Generation). Plugin-based architecture with direct API calls to OpenAI/Anthropic/Ollama/Bedrock and support for Qdrant, Pinecone, S3 Vectors, and more.

---

## Features

- **Capture thoughts** - Quick note-taking, instantly searchable
- **Import documents** - PDF, EPUB, Markdown, DOCX, PPTX, VTT/SRT transcripts
- **Semantic search** - Find things by meaning, not just keywords
- **AI answers** - Ask questions, get synthesized answers from your documents
- **Namespaces** - Organize into nested categories
- **One command** - `docker-compose up` and you're running

### Extensible Provider Architecture

Add custom providers without modifying core code. Built-in support for Anthropic, OpenAI, AWS Bedrock, Qdrant, Pinecone, ChromaDB, and more. Install third-party providers via pip, or create your own.

Example:
```bash
# Install a third-party provider
pip install stache-milvus

# Configure it
export VECTORDB_PROVIDER=milvus

# Done - providers are auto-discovered
```

See [docs/plugins.md](docs/plugins.md) for details.

---

## Provider Comparison

Stache supports multiple vector database providers. Here's what works on each:

| Feature | Qdrant | S3 Vectors |
|---------|--------|------------|
| Semantic search | ✅ Fast | ✅ Fast |
| Document ingestion | ✅ | ✅ |
| Question answering | ✅ | ✅ |
| Document discovery | ✅ | ✅ |
| List documents (summaries) | ✅ | ✅ |
| Delete by doc_id | ✅ | ✅ (slower) |
| Get document by ID | ✅ | ✅ (via DynamoDB) |
| Legacy document listing | ✅ | ✅ (via DynamoDB) |
| Database export | ✅ | ⚠️ Limited |
| Orphaned chunk cleanup | ✅ | N/A (no orphans) |

**S3 Vectors** - Good for:
- All core RAG features (search, ingest, answer)
- Production deployments
- Serverless/Lambda environments
- Cost-effective scale

**Qdrant** - Good for:
- Everything (full feature set)
- Local development
- Self-hosted deployments
- Database backup/export

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- API key from [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/stache-ai/stache-ai.git
cd stache

# 2. Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY or OPENAI_API_KEY

# 3. Start Stache
docker-compose up -d

# 4. Open the UI
open http://localhost:8000
```

That's it.

### Use with Claude (MCP)

Connect Stache to Claude Desktop/Code for AI-powered knowledge retrieval:

→ **[stache-tools setup guide](https://github.com/stache-ai/stache-tools#quick-start)**

Windows users: Download `stache-mcp.exe` from [releases](https://github.com/stache-ai/stache-tools/releases) - no Python needed.

### Docker Hub

Skip the build and pull directly from Docker Hub:

```bash
# Full image (with OCR support for scanned PDFs)
docker pull stacheai/stache-ai:latest

# Slim image (without OCR, ~230MB smaller)
docker pull stacheai/stache-ai:slim
```

Then run with docker-compose by updating `docker-compose.yml`:

```yaml
app:
  image: stacheai/stache-ai:latest  # or :slim
  # ... rest of config
```

| Tag | OCR | Size | Use Case |
|-----|-----|------|----------|
| `latest`, `0.1.0` | Yes | ~715MB | Full featured, scanned PDF support |
| `slim`, `0.1.0-slim` | No | ~485MB | Smaller image, text-based docs only |

### Docker Build Options

Customize your build with these options:

```bash
# Default build (all providers, with OCR)
docker compose build

# Airgap build (Qdrant, Ollama, MongoDB only - no cloud APIs)
docker compose build --build-arg INSTALL_PROFILE=airgap

# AWS build (Bedrock, S3 Vectors, DynamoDB)
docker compose build --build-arg INSTALL_PROFILE=aws

# Minimal build (core only, bring your own providers)
docker compose build --build-arg INSTALL_PROFILE=minimal

# Disable OCR support (saves ~230MB)
docker compose build --build-arg WITH_OCR=false

# Combine options
docker compose build --build-arg INSTALL_PROFILE=airgap --build-arg WITH_OCR=false
```

| Profile | Providers Included | Use Case |
|---------|-------------------|----------|
| `full` (default) | All providers | Maximum compatibility |
| `airgap` | Qdrant, Ollama, MongoDB | Offline/private deployments |
| `aws` | Bedrock, S3 Vectors, DynamoDB | AWS-native deployments |
| `minimal` | Core only | Custom provider setups |

---

## Usage

### Capture a Thought

```bash
# Via Web UI
Open http://localhost:8000 and click "Capture"

# Via API
curl -X POST http://localhost:8000/api/capture \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Kubernetes uses etcd for distributed consensus and stores all cluster state there.",
    "metadata": {
      "tags": ["kubernetes", "architecture"],
      "source": "K8s docs"
    }
  }'
```

### Query Your Knowledge

```bash
# Via Web UI
Open http://localhost:8000 and ask a question

# Via API
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How does Kubernetes handle distributed consensus?",
    "top_k": 5
  }'
```

### Import Documents

```bash
# Via Web UI (supports multiple files)
Open http://localhost:8000 → Upload → Drag & drop files

# Via CLI (for bulk directory imports)
docker exec -it stache-app stache-import ./docs --namespace my-docs
```

---

## CLI

Bulk import directories of documents.

### Basic Import

```bash
# Import all supported files from a directory
stache-import /path/to/docs --namespace my-docs

# Or via Docker
docker exec -it stache-app stache-import /data/docs --namespace my-docs
```

### Import with Pattern Matching

```bash
# Import only markdown files
stache-import ./docs -n notes -p "*.md"

# Import recursively (include subdirectories)
stache-import ./docs -n notes -p "*.md" -r
```

### Import with Custom Metadata

```bash
# Add metadata to all imported documents
stache-import ./talks -n church/talks \
  -m speaker="Jane Doe" \
  -m year=2024

# Prepend metadata to chunks for better semantic search
stache-import ./lectures -n lectures \
  -m speaker="Dr. Smith" \
  --prepend-metadata speaker
```

### Chunking Strategies

```bash
# Use markdown chunking for .md files
stache-import ./docs -n docs -c markdown

# Use transcript chunking for VTT/SRT files
stache-import ./transcripts -n lectures -c transcript
```

Available strategies: `recursive` (default), `hierarchical`, `markdown`, `semantic`, `character`, `transcript`

### Dry Run & Error Handling

```bash
# Preview what would be imported (no actual import)
stache-import ./docs -n test --dry-run

# Continue on errors instead of stopping
stache-import ./mixed-docs -n docs --skip-errors

# Verbose output
stache-import ./docs -n docs -v
```

### CLI Options Reference

```
stache-import PATH [OPTIONS]

Arguments:
  PATH                    Directory containing documents to import

Options:
  -n, --namespace TEXT    Target namespace (required)
  -p, --pattern TEXT      Glob pattern for files (default: *)
  -r, --recursive         Search subdirectories
  -c, --chunking TEXT     Chunking strategy (default: recursive)
  -m, --metadata TEXT     Add metadata as key=value (repeatable)
  --prepend-metadata TEXT Comma-separated metadata keys to prepend to chunks
  --dry-run               Show what would be imported
  --skip-errors           Continue on errors
  -v, --verbose           Verbose output
  --help                  Show help
```

### Supported File Types

- **Text**: `.txt`, `.md`, `.markdown`
- **Documents**: `.pdf`, `.docx`, `.pptx`
- **Ebooks**: `.epub`
- **Transcripts**: `.vtt`, `.srt`

---

## Architecture

```
┌─────────────────────────────────┐      ┌─────────────┐
│         App Container           │─────▶│   Qdrant    │
│  Vue Frontend + FastAPI Backend │      │  (Vector DB)│
│          Port 8000              │      │  Port 6333  │
└─────────────────────────────────┘      └─────────────┘
                 │
                 ▼
          ┌─────────────┐
          │ LLM Provider│
          │Claude / GPT │
          └─────────────┘
```

**Components:**

- **App**: Single container serving Vue frontend + FastAPI backend on port 8000
- **Vector DB**: Qdrant for semantic search
- **LLM**: Claude, GPT, or Ollama for answer synthesis

---

## Development

### Run locally without Docker

**Backend:**
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install core package and providers you need
pip install -e packages/stache-ai
pip install -e packages/stache-ai-qdrant
pip install -e packages/stache-ai-ollama

# Start Qdrant separately (Docker)
docker run -p 6333:6333 qdrant/qdrant

# Run backend
uvicorn stache_ai.api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
source venv/bin/activate
pip install -e "packages/stache-ai[dev]"

# Run all tests
pytest packages/stache-ai/tests

# Run with coverage report
pytest --cov=stache_ai --cov-report=html

# Run specific test file
pytest packages/stache-ai/tests/test_chunking.py -v
```

### Project Structure

```
stache/
├── packages/                    # Python packages (monorepo)
│   ├── stache-ai/               # Core package
│   │   └── src/stache_ai/
│   │       ├── api/             # FastAPI routes
│   │       ├── rag/             # RAG pipeline
│   │       ├── loaders/         # Document loaders
│   │       └── cli/             # CLI tools
│   ├── stache-ai-qdrant/        # Qdrant provider
│   ├── stache-ai-ollama/        # Ollama provider
│   ├── stache-ai-openai/        # OpenAI provider
│   ├── stache-ai-anthropic/     # Anthropic provider
│   ├── stache-ai-bedrock/       # AWS Bedrock provider
│   ├── stache-ai-s3vectors/     # S3 Vectors provider
│   ├── stache-ai-dynamodb/      # DynamoDB provider
│   ├── stache-ai-mongodb/       # MongoDB provider
│   └── ...                      # More providers
│
├── frontend/                    # Vue frontend
│   ├── src/
│   │   ├── components/          # UI components
│   │   ├── pages/               # Pages
│   │   └── api/                 # API client
│   └── package.json
│
├── data/                        # Persistent data (gitignored)
├── docker-compose.yml           # One-command deployment
├── Dockerfile                   # Multi-profile build
├── .env.example                 # Configuration template
└── README.md
```

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT License - see [LICENSE](LICENSE) for details

---

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Backend API
- [Qdrant](https://qdrant.tech/) - Vector database
- [Vue.js](https://vuejs.org/) - Frontend
- [Claude](https://www.anthropic.com/claude) / [GPT](https://openai.com/) / [Ollama](https://ollama.ai/) - LLM providers
