# stache-ai-documents

Document format loaders for Stache AI.

Provides loaders for EPUB, DOCX (Word), and PPTX (PowerPoint) files.

## Installation

```bash
pip install stache-ai-documents
```

## Supported Formats

- **EPUB** - eBook format
- **DOCX** - Microsoft Word documents
- **PPTX** - Microsoft PowerPoint presentations

## Usage

Once installed, the loaders automatically register and handle their respective file types:

```python
from stache_ai.loaders import load_document

# EPUB
text = load_document("book.epub")

# DOCX
text = load_document("document.docx")

# PPTX
text = load_document("presentation.pptx")
```

The loaders extract text content while preserving document structure where appropriate.
