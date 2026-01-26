# Changelog

All notable changes to stache-ai-enrichment will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-01-25

### Added

- Organization suggestions feature in `SummaryEnricher` - can now suggest filename and namespace based on document content when `_suggest_organization=True` is set in metadata
- Dynamic schema extension for organization suggestions with `suggested_filename` and `suggested_namespace` fields
- Namespace list integration in enrichment prompts for better namespace matching

## [0.1.0] - 2025-12-25

### Added

- Initial release
- AI-powered metadata enrichment (summary, doc_type, chunking_strategy)
- `SummaryEnricher` with AWS Bedrock Nova Lite support
