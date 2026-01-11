# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-01-11

### Added
- `load_with_metadata()` method returning structured `OcrLoadResult` dataclass
- Sophisticated OCR heuristic using chars/page < 50 threshold (better scanned PDF detection)
- Configurable timeout support via `STACHE_OCR_TIMEOUT` env var (default 300s)
- Rich metadata: `page_count`, `char_count`, `chars_per_page`, `ocr_used`, `ocr_failed`, `ocr_method`, `error_reason`
- `OcrLoadResult.to_dict()` method for serialization
- Comprehensive test suite (70+ tests covering integration, edge cases, and metadata accuracy)

### Changed
- `load()` now delegates to `load_with_metadata().text` (backward compatible)
- OCR heuristic improved: detects sparse-text PDFs (not just empty ones)
- Better error handling with graceful degradation on OCR failures

### Fixed
- Better detection of scanned PDFs (was missing sparse-text documents)
- Timeout protection prevents Lambda hangs on complex PDFs
- Missing ocrmypdf binary now gracefully falls back to text extraction

## [0.1.0] - 2025-12-31

### Added
- Initial release
- Basic OCR support for scanned PDFs using pdfplumber and ocrmypdf
- OcrPdfLoader entry point for stache.loader plugin system
- Detection of scanned PDFs for automatic OCR processing
