# Changelog

All notable changes to stache-ai-ollama will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-04

### Added

- **`context=` parameter**: `OllamaReranker.rerank()` accepts an optional keyword-only `context` parameter (request context passed through from stache-ai's pipeline). This provider ignores it.

### Requires

- `stache-ai>=0.3.0`

## [0.1.1] - 2026-01-16

### Changed

- LLM provider improvements for structured output support

## [0.1.0] - 2025-12-25

### Added

- Initial release
- Ollama LLM provider for Stache AI
- Ollama embedding provider
- Ollama reranker provider
- Support for local model inference
