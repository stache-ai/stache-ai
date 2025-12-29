# stache-ai-aws

AWS providers bundle for [Stache AI](https://github.com/stache-ai/stache-ai).

This metapackage installs all AWS-based providers for Stache:
- **stache-ai-bedrock** - LLM and Embedding via AWS Bedrock
- **stache-ai-dynamodb** - Namespace and Document Index via DynamoDB
- **stache-ai-s3vectors** - Vector storage via S3 Vectors

## Installation

```bash
pip install stache-ai-aws
```

This is equivalent to:
```bash
pip install stache-ai-bedrock stache-ai-dynamodb stache-ai-s3vectors
```

## Usage

```python
from stache_ai.config import Settings

settings = Settings(
    llm_provider="bedrock",
    embedding_provider="bedrock",
    vectordb_provider="s3vectors",
    namespace_provider="dynamodb",
    document_index_provider="dynamodb"
)
```
