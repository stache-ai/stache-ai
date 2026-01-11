# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records for stache-ai-ocr. Each ADR documents a significant design decision, the context that led to it, and the consequences of that decision.

## Format

ADRs follow the standard Architecture Decision Record format:
- **Status**: Current state (Proposed, Accepted, Deprecated, Superseded)
- **Context**: The situation that prompted the decision
- **Decision**: What was decided
- **Consequences**: Positive outcomes and trade-offs

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [001](./001-keep-pdfplumber.md) | Keep pdfplumber for Text Extraction | Accepted | 2026-01-11 |

## Adding New ADRs

When documenting a new decision:

1. Create a new file: `NNN-descriptive-title.md` (use next sequential number)
2. Follow the standard format from existing ADRs
3. Reference this README from your ADR
4. Update the index above
5. Link from relevant documentation (README.md, etc.)

## References

- [Architecture Decision Records (ADR) Overview](https://adr.github.io/)
- stache-ai-ocr README for implementation details
