# stache-ai-enrichment

AI-powered metadata enrichment for Stache (standard features).

## Features

Automatically enriches document metadata with:

- **Summary**: 2-3 sentence summary of document content and purpose
- **Document Type**: Classification (article, guide, tutorial, reference, etc.)
- **Chunking Strategy**: Recommended chunking strategy based on document structure

## Installation

```bash
pip install stache-ai-enrichment
```

The enricher automatically registers via entry points - no configuration needed.

## Cost

Approximately $0.0005 per document using Nova Lite (default model).

## Requirements

- `stache-ai>=0.1.6` (includes BaseAIEnricher and LLM structured output support)
- Bedrock LLM provider with Nova or Claude models

## Coexistence with Enterprise Plugin

This plugin can coexist with `stache-ai-enrichment-enterprise`:

- Standard plugin: priority=80, extracts basic fields
- Enterprise plugin: priority=85, extracts advanced fields (concepts, entities, relationships)
- Enterprise plugin detects standard plugin and avoids duplicate LLM calls

## License

MIT
