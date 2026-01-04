# Stache v0.1.0 - Initial Release

**Release Date**: December 23, 2025

## Overview

Stache is **storage for AI** - a flexible, production-ready infrastructure layer that gives AI systems persistent memory and knowledge retrieval capabilities through Retrieval-Augmented Generation (RAG).

## What is Stache?

Stache is storage infrastructure for AI that provides:
- **Document ingestion** from any source (PDFs, text, web, APIs, databases)
- **Semantic search** with vector similarity and optional AI synthesis
- **Structured storage** with namespaces, metadata, and organization
- **Provider flexibility** via plugin architecture (swap LLMs, embeddings, vector DBs)
- **AI integration** through MCP (Model Context Protocol), REST API, and Python SDK

Think of it as a database for AI - not just storing data, but making it retrievable and useful for AI systems.

## New in This Release

### Project Rename 🎯
- **New Name**: Stache (mustache emoji: 🥸)
- **PyPI Package**: `stache-ai` (install with `pip install stache-ai`)
- **Import Name**: `from stache import ...`
- **CLI Command**: `stache`
- **GitHub Organization**: `stache-ai/*`

### Core Features ✨

#### 1. Plugin Architecture
- **6 Provider Types**: LLM, Embeddings, Vector DB, Namespace, Reranker, Document Index
- **Entry Points**: All providers discoverable via `stache.*` entry point groups
- **Built-in Providers**:
  - **LLMs**: Anthropic (Claude), OpenAI (GPT), Bedrock, Ollama, Fallback
  - **Embeddings**: OpenAI, Bedrock (Cohere), Ollama, Mixedbread, Fallback
  - **Vector DBs**: Qdrant, Pinecone, Chroma, S3 Vectors
  - **Namespaces**: DynamoDB, MongoDB, Redis, SQLite
  - **Rerankers**: Simple, Cohere, Ollama
  - **Document Index**: DynamoDB, MongoDB

#### 2. MCP Integration 🔌
Connect Stache to Claude Desktop for seamless knowledge base access:
- **Tools**: `search`, `ingest_text`, `list_namespaces`, `list_documents`, `get_document`
- **Authentication**: Cognito OAuth with automatic token refresh
- **Package**: Install `stache-mcp` for MCP server

#### 3. Production AWS Deployment ☁️
- **Lambda**: FastAPI app running on AWS Lambda
- **API Gateway**: RESTful API with Cognito authentication
- **S3 Vectors**: Serverless vector storage
- **DynamoDB**: Document index and namespace registry
- **Bedrock**: Claude 3.5 Sonnet + Cohere embeddings
- **One-command deploy**: `./deploy.sh` in `stache-serverless` repo

#### 4. Document Processing 📄
- **Formats**: PDF, DOCX, PPTX, Markdown, HTML, TXT, eBooks (EPUB)
- **Chunking Strategies**: Recursive, semantic, hierarchical, markdown-aware, transcript
- **Metadata**: Automatic extraction and custom tagging
- **Batch Import**: CLI tool for bulk ingestion

#### 5. Advanced Features 🚀
- **Semantic Search**: Vector similarity with optional AI synthesis
- **Metadata Filtering**: Query by namespace, tags, document properties
- **Reranking**: Optional re-ranking for improved relevance
- **Namespace Management**: Organize documents into logical collections
- **Pending Queue**: Stage documents before committing to vector DB
- **Health Checks**: Monitor provider status and connectivity

## Installation

### Main Package
```bash
pip install stache-ai
```

### MCP Server (for Claude Desktop)
```bash
pip install stache-mcp
```

### From Source
```bash
git clone https://github.com/stache-ai/stache-ai.git
cd stache/backend
pip install -e ".[dev]"
```

## Quick Start

### 1. Ingest Documents
```bash
# Import a directory of PDFs
stache import ~/Documents/papers --namespace research

# Import a single file with metadata
stache import article.pdf --namespace articles --tags ai,ml
```

### 2. Search Your Knowledge Base
```bash
# Search across all namespaces
stache search "machine learning best practices"

# Search with namespace filter
stache search "neural networks" --namespace research

# Get AI-synthesized answer
stache search "summarize recent AI trends" --synthesize
```

### 3. Manage Namespaces
```bash
# List all namespaces
stache namespaces list

# Create a namespace
stache namespaces create --name projects --description "Work projects"

# Export namespace metadata
stache namespace-export research > research-backup.json
```

### 4. Use with Claude Desktop (MCP)
Configure in `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "stache": {
      "command": "stache-mcp",
      "env": {
        "STACHE_URL": "https://your-api.execute-api.us-east-1.amazonaws.com",
        "STACHE_API_KEY": "your-api-key"
      }
    }
  }
}
```

Then ask Claude: "Search my Stache knowledge base for information about..."

## Technical Highlights

### Architecture
- **Backend**: FastAPI + Pydantic v2
- **Testing**: 564 tests passing with pytest
- **Type Safety**: Full mypy type checking
- **Code Quality**: Ruff linting and formatting
- **Async/Await**: Asynchronous provider operations
- **Configuration**: Environment-based with pydantic-settings

### Provider Pattern
```python
from stache.providers.factories import LLMProviderFactory

# Built-in providers auto-discovered via entry points
llm = LLMProviderFactory.create(config)  # Uses LLM_PROVIDER env var

# List available providers
providers = LLMProviderFactory.get_available_providers()
# ['anthropic', 'openai', 'bedrock', 'ollama', 'fallback']
```

### Custom Providers
Create your own provider plugins:
```toml
# pyproject.toml
[project.entry-points."stache.vectordb"]
my_db = "my_package.provider:MyVectorDBProvider"
```

See `docs/plugins.md` for full guide.

## Performance

- **S3 Vectors**: Serverless, scales automatically, pay-per-use
- **Cohere Embeddings**: 1024 dimensions, optimized for semantic search
- **DynamoDB**: Single-digit millisecond latency for namespace lookups
- **Lambda**: Cold start < 2s, warm requests < 500ms
- **Batch Processing**: Parallel embedding generation

## Known Limitations

1. **S3 Vectors**: `list_vectors` doesn't support metadata filtering (use `query_vectors`)
2. **Text Metadata**: Must be marked as non-filterable (exceeds 2KB limit)

See `CLAUDE.md` "Critical Lessons" section for details.

## What's Next

### Upcoming Features
- [ ] GitHub repository publication
- [ ] PyPI package publication
- [ ] Docker image on Docker Hub
- [ ] Multi-user support with auth
- [ ] Web UI improvements (React migration)
- [ ] Streaming responses
- [ ] Document versioning
- [ ] Citation tracking

### Roadmap
- **v0.2.0**: Enhanced web UI, streaming, better error handling
- **v0.3.0**: Multi-tenancy, user management, access control
- **v0.4.0**: Advanced analytics, usage dashboards
- **v1.0.0**: Production-hardened, enterprise features

## Contributing

We welcome contributions! See `CONTRIBUTING.md` for:
- Development setup
- Code style guidelines
- Testing requirements
- PR process

## Documentation

- **README**: Project overview and quick start
- **CONTRIBUTING**: Development guide
- **CLAUDE.md**: Internal development context
- **docs/plugins.md**: Provider plugin guide
- **docs/mcp-setup.md**: MCP integration guide

## Support

- **Issues**: https://github.com/stache-ai/stache-ai/issues
- **Discussions**: https://github.com/stache-ai/stache-ai/discussions

## License

MIT License - see LICENSE file for details

## Acknowledgments

Built with:
- FastAPI, Pydantic, Click
- Anthropic Claude API
- AWS Bedrock, S3 Vectors, DynamoDB
- Qdrant, Pinecone, Chroma
- OpenAI, Cohere, Ollama
- MCP (Model Context Protocol)

---

**Install now**: `pip install stache-ai`

**Star the repo**: https://github.com/stache-ai/stache-ai ⭐
