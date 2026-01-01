# stache-ai-ocr

OCR support for Stache AI document loaders.

Provides a high-priority PDF loader that falls back to OCR for scanned documents.

## Installation

```bash
pip install stache-ai-ocr
apt install ocrmypdf  # System dependency required
```

## Usage

Once installed, the OCR loader automatically registers and takes priority over the basic PDF loader for all PDF files.

The loader will:
1. First attempt normal text extraction with pdfplumber
2. If no text is found (scanned PDF), fall back to OCR using ocrmypdf
3. Gracefully handle missing ocrmypdf (logs warning and returns empty text)

## System Requirements

- **ocrmypdf** system binary must be installed
  - Ubuntu/Debian: `apt install ocrmypdf`
  - macOS: `brew install ocrmypdf`
  - Includes Tesseract OCR engine

## Priority Override

This loader registers with priority 10, overriding the basic PDF loader (priority 0). This ensures OCR is used when available without affecting systems where it's not installed.
