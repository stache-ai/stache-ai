# OCR Test Corpus

This directory contains a representative set of PDF files for regression testing the stache-tools-ocr plugin.

## Overview

**Total Size**: ~672 KB (6 files)

These PDFs cover common document types and edge cases encountered in real-world OCR workflows. Each is designed to test specific aspects of the OCR pipeline.

## PDF Inventory

### 01-text-based.pdf
- **Category**: Text-based / Born-digital
- **Size**: 48 KB
- **Pages**: 1
- **Expected Behavior**: No OCR needed; standard text extraction via pypdf
- **Content**: Multiple paragraphs with standard formatting, numbers, and symbols
- **Test Purpose**: Baseline test to ensure normal text extraction isn't broken by OCR logic
- **License**: Generated (Public Domain)

### 02-empty.pdf
- **Category**: Edge case / Empty document
- **Size**: 9 KB
- **Pages**: 1 (blank)
- **Expected Behavior**: Safe no-op; should return empty content without errors
- **Content**: Completely blank page
- **Test Purpose**: Verify robustness with minimal/empty content
- **License**: Generated (Public Domain)

### 03-single-page.pdf
- **Category**: Minimal document
- **Size**: 19 KB
- **Pages**: 1
- **Expected Behavior**: Standard text extraction
- **Content**: Single page with title and brief text
- **Test Purpose**: Baseline for single-page documents; ensures efficient processing
- **License**: Generated (Public Domain)

### 04-scanned.pdf
- **Category**: Scanned/Image-based
- **Size**: 33 KB
- **Pages**: 1
- **Expected Behavior**: OCR required; text extraction via Tesseract
- **Content**: Text rendered as image pixels (no embedded text layer)
- **Test Purpose**: Core test case; validates OCR detection and processing
- **License**: Generated (Public Domain)

### 05-large-multipage.pdf
- **Category**: Performance testing / Multi-page
- **Size**: 490 KB
- **Pages**: 11
- **Expected Behavior**: Standard text extraction for all pages; performance baseline
- **Content**: 11 pages of text content (Lorem ipsum + indexed content)
- **Test Purpose**: Performance regression testing; ensures scaling doesn't degrade
- **License**: Generated (Public Domain)

### 06-hybrid.pdf
- **Category**: Mixed content / Hybrid
- **Size**: 60 KB
- **Pages**: 2
- **Expected Behavior**: Page 1 standard extraction, Page 2 OCR processing
- **Content**:
  - Page 1: Born-digital text
  - Page 2: Scanned/image content
- **Test Purpose**: Real-world scenario testing; handles mixed document types
- **License**: Generated (Public Domain)

## Regression Testing Strategy

### Baseline Metrics to Track

For each test file, establish and monitor:

| File | Metric | Expected | Purpose |
|------|--------|----------|---------|
| 01-text-based.pdf | Text extraction accuracy | 100% | Ensure non-OCR path works |
| 02-empty.pdf | Error-free processing | Yes | Robustness |
| 03-single-page.pdf | Processing time | <100ms | Single-page baseline |
| 04-scanned.pdf | OCR detection | Detected | Core OCR validation |
| 05-large-multipage.pdf | Page count accuracy | 11 pages | Multi-page handling |
| 06-hybrid.pdf | Mixed processing | Both modes work | Real-world scenario |

### Testing Scenarios

1. **Text Extraction Only**: 01, 03, 05 should work without OCR
2. **OCR Detection**: 04, 06 should trigger OCR enrichment
3. **Edge Cases**: 02 (empty) should not crash
4. **Performance**: 05 (11 pages) should process efficiently
5. **Content Accuracy**: All files should return extractable content

## Usage

### In Tests

```python
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pdfs"

@pytest.mark.parametrize("pdf_file", FIXTURES_DIR.glob("*.pdf"))
def test_ocr_plugin(pdf_file):
    """Test OCR enricher with each fixture."""
    enricher = OCREnricher()
    result = enricher.process(pdf_file.read_bytes(), {})
    assert result is not None
```

### Updating Fixtures

To regenerate all PDFs:

```bash
cd tests/fixtures
python3 create_test_pdfs.py
```

## Technical Details

### PDF Generation

All PDFs are generated using Python's PIL (Pillow) library:
- Images rendered at 612x792 pixels (US Letter size)
- Text rendered using DejaVu Sans font (or default if unavailable)
- Scanned PDFs use light gray background (#f5f5f5) to simulate aging
- Multi-page PDFs use PIL's `save_all` with `append_images`

### File Format Notes

- **Format**: PDF (image-based, no embedded text layers except where noted)
- **Compression**: Default PIL/PDF compression
- **Encoding**: UTF-8 for any embedded metadata

## Future Enhancements

1. **Real Scanned Books**: Consider adding a page from Project Gutenberg scanned book archive
2. **Multilingual Content**: Add PDFs with non-ASCII characters (CJK, Arabic, etc.)
3. **Complex Layouts**: Add PDF with columns, tables, or complex formatting
4. **Compressed Content**: Test with highly compressed/low-quality scans
5. **Metadata Testing**: Add PDFs with author/title/creation date metadata

## License

All test PDFs in this directory are generated for testing purposes and are in the public domain. They may be freely used, modified, and distributed.

---

**Last Updated**: January 11, 2026
**Generator Script**: `create_test_pdfs.py`
**Total Corpus Size**: 672 KB
