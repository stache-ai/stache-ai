# ADR 001: Keep pdfplumber for stache-ai-ocr Text Extraction

**Status**: Accepted

**Date**: 2026-01-11

**Decision Maker**: Principal Engineer Review

---

## Context

The stache-ai-ocr package currently uses `pdfplumber` for PDF text extraction. During an initial refactor planning session, a proposal emerged to switch to `pypdf` for consistency with the client-side implementation in stache-tools-ocr (which uses `pypdf` for the CLI).

### Current State

| Component | Library | Role |
|-----------|---------|------|
| **stache-ai-ocr** (server) | pdfplumber | Main text extraction + OCR fallback |
| **stache-tools-ocr** (client CLI) | pypdf | OCR detection heuristics |

Both packages provide complementary PDF handling:
- `stache-ai-ocr`: Processes PDFs during backend ingestion (UI upload flow)
- `stache-tools-ocr`: Provides CLI enrichment for scanned PDF detection and OCR

### The Refactor Proposal

Initial analysis suggested switching stache-ai-ocr to `pypdf` for:
- Reduced library diversity
- Theoretical simplification of dependencies
- Consistent PDF handling across packages

### PE Review Finding

Principal Engineer review identified a **regression risk** with this change:
- pdfplumber has superior text extraction quality
- Proven production reliability in existing UI upload flow
- pypdf is adequate for the detection heuristic in stache-tools-ocr (counts chars/page)
- Quality mismatch between packages is **not a problem** if each is well-suited to its role

---

## Decision

**Keep pdfplumber in stache-ai-ocr.**

Accept the small library diversity between packages. The tradeoff favors:
1. **Higher quality text extraction** (backend critical path)
2. **Proven production reliability** (no regression risk)
3. **Role-specific optimization** (pypdf handles detection well enough)

---

## Consequences

### Positive

✅ **Better text extraction quality**: pdfplumber's layout-aware extraction preserves document structure better than pypdf

✅ **No regression risk**: Production upload flow continues using proven code path

✅ **Role-specific optimization**: Each library is optimally suited to its use case
  - pdfplumber: Complex document ingestion (backend)
  - pypdf: Simple char-count heuristic (client detection)

✅ **Minimal adapter overhead**: stache-tools' interface adapter (BinaryIO → temp file) is negligible

✅ **Flexibility for future improvements**: Can independently upgrade each library for its specific needs

### Trade-offs

⚠️ **Library diversity**: Two PDF libraries instead of one unified approach
  - **Acceptable because**: Different use cases justify different tools
  - **Cost**: Developers need to understand both libraries
  - **Mitigation**: Clear documentation of why each exists

⚠️ **Dependency size**: Slightly larger installation footprint with both libraries
  - **Cost**: ~2MB additional installation size
  - **Mitigation**: Both are pure Python with minimal dependencies

⚠️ **Maintenance burden**: Two libraries means two upgrade cycles
  - **Cost**: Quarterly update review for both
  - **Mitigation**: Both are mature, stable libraries with regular releases

---

## Implementation Notes

### No Code Changes Required

This decision confirms the current architecture. No refactoring needed.

### Documentation Updates

- Mark this pattern in stache-ai-ocr README as intentional
- Document in stache-tools-ocr why pypdf is appropriate for detection
- Add entry to CLAUDE.md critical lessons (if community-facing decision)

### Future Review Points

Revisit this decision if:
1. **pdfplumber extraction quality degrades** relative to pypdf
2. **pypdf significantly improves** text extraction quality
3. **New PDF processing needs** emerge that justify consolidation
4. **Dependency conflicts arise** between the two libraries

---

## Rationale

This decision prioritizes **correctness over uniformity**:

> "Use the best tool for the job, not the most uniform tool."

In a knowledge base system, text extraction quality directly impacts search relevance and user experience. The 2MB additional dependency cost and modest learning curve (developers already study multiple libraries) is far outweighed by extraction quality.

The PE review correctly identified that library diversity is a non-issue when each library serves a well-defined purpose and excels in its domain.

---

## References

- PE Review: Principal Engineer review of stache-ai-ocr implementation (January 2026)
- Issue: Initial refactor plan proposing pypdf consolidation
- Related ADRs: None

---

## Questions for Future Sessions

1. Has pdfplumber improved to match pypdf extraction quality? (Annual review)
2. Are users reporting extraction quality issues that warrant pypdf investigation?
3. Would a benchmark suite help justify/validate this decision? (Future enhancement)
