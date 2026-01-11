# Stache API Reference

**Version:** 0.1.0
**Base URL:** `/api`

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Common Response Patterns](#common-response-patterns)
4. [Error Handling](#error-handling)
5. [Endpoints](#endpoints)
   - [Health](#health)
   - [Query](#query)
   - [Upload](#upload)
   - [Capture](#capture)
   - [Documents](#documents)
   - [Namespaces](#namespaces)
   - [Pending Queue](#pending-queue)
   - [Insights](#insights)
   - [Models](#models)
6. [Best Practices](#best-practices)

---

## Overview

The Stache API is a FastAPI-based REST API for managing a knowledge base with semantic search, document ingestion, and AI-powered query synthesis. It provides endpoints for uploading documents, capturing notes, querying the knowledge base, and managing namespaces for multi-tenant or multi-project organization.

**Key Features:**
- Semantic search with optional AI synthesis
- Multi-format document ingestion (PDF, DOCX, PPTX, XLSX, EPUB, Markdown, etc.)
- Namespace-based organization
- Document management and deletion
- Metadata filtering
- Batch operations

---

## Authentication

### AWS Cognito JWT

When deployed on AWS, the API uses **AWS Cognito JWT authentication** via API Gateway:

- **Token Type:** Bearer token
- **Header:** `Authorization: Bearer <jwt_token>`
- **Issuer:** AWS Cognito User Pool
- **Validation:** Performed by API Gateway before requests reach the Lambda function

**Example Request:**
```bash
curl -H "Authorization: Bearer eyJraWQ..." \
     https://api.stache.example.com/api/query \
     -X POST -H "Content-Type: application/json" \
     -d '{"query": "what is RAG?"}'
```

### Local Development

For local development without authentication:
- No authentication required when running locally
- Configure CORS via `CORS_ORIGINS` environment variable

---

## Common Response Patterns

### Success Response
```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": { ... }
}
```

### Pagination Response
```json
{
  "items": [...],
  "count": 25,
  "total": 150,
  "next_key": "eyJkb2NfaWQiOiAiLi4uIn0="
}
```

### Document Metadata
```json
{
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "report.pdf",
  "namespace": "default",
  "chunk_count": 42,
  "created_at": "2025-01-10T12:00:00Z",
  "headings": ["Introduction", "Chapter 1", "Conclusion"]
}
```

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| 200 | OK | Successful request |
| 400 | Bad Request | Invalid parameters or malformed request |
| 404 | Not Found | Resource doesn't exist |
| 500 | Internal Server Error | Server-side error |
| 501 | Not Implemented | Feature not supported by current provider |

### Error Response Format
```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Errors

**Provider Capability Error (501):**
```json
{
  "detail": "This operation is only available for Qdrant. S3 Vectors users: summaries are created automatically during document ingestion."
}
```

**Not Found (404):**
```json
{
  "detail": "Document not found: 550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Endpoints

### Health

#### `GET /ping`
Lightweight connectivity check - no backend calls.

**Response:**
```json
{
  "ok": true
}
```

---

#### `GET /health`
Full health check - validates all provider connections.

**Response (Healthy):**
```json
{
  "status": "healthy",
  "providers": {
    "llm": "bedrock",
    "embedding": "bedrock",
    "vectordb": "s3vectors",
    "namespace": "dynamodb"
  },
  "vectordb_provider": "s3vectors"
}
```

**Response (Unhealthy):**
```json
{
  "status": "unhealthy",
  "error": "Service initialization failed"
}
```

---

### Query

#### `POST /api/query`
Query the knowledge base with natural language.

**Request Body:**
```json
{
  "query": "what is retrieval augmented generation?",
  "top_k": 20,
  "synthesize": true,
  "namespace": "default",
  "rerank": true,
  "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
  "filter": {
    "source": "meeting notes",
    "date": "2025-01"
  }
}
```

**Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language search query |
| `top_k` | integer | No | 20 | Number of results to return (max relevant chunks) |
| `synthesize` | boolean | No | true | If true, returns AI-synthesized answer; if false, returns raw search results |
| `namespace` | string | No | null | Optional namespace to search within |
| `rerank` | boolean | No | true | Whether to rerank results for better relevance and deduplication |
| `model` | string | No | null | Override default LLM model for synthesis (Bedrock model ID) |
| `filter` | object | No | null | Metadata filter (e.g., `{"source": "meeting notes"}`) |

**Response (synthesize=true):**
```json
{
  "answer": "Retrieval Augmented Generation (RAG) is a technique that combines...",
  "sources": [
    {
      "text": "RAG combines retrieval and generation...",
      "metadata": {
        "filename": "rag-guide.pdf",
        "page": 3,
        "doc_id": "550e8400-e29b-41d4-a716-446655440000"
      },
      "score": 0.89
    }
  ],
  "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
}
```

**Response (synthesize=false):**
```json
{
  "results": [
    {
      "text": "RAG combines retrieval and generation...",
      "metadata": {
        "filename": "rag-guide.pdf",
        "page": 3,
        "doc_id": "550e8400-e29b-41d4-a716-446655440000"
      },
      "score": 0.89
    }
  ],
  "count": 15
}
```

---

### Upload

#### `POST /api/upload`
Upload and ingest a single document with automatic format detection.

**Request:** Multipart form data

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `file` | file | Yes | - | File to upload |
| `chunking_strategy` | string | No | "auto" | Chunking strategy (see below) |
| `metadata` | object | No | {} | Additional metadata as JSON |
| `namespace` | string | No | "default" | Target namespace |
| `prepend_metadata` | string | No | null | Comma-separated metadata keys to prepend to chunks |

**Supported File Formats:**
- Text: `.txt`, `.md`
- Documents: `.pdf`, `.docx`, `.pptx`, `.xlsx`
- Ebooks: `.epub`
- Transcripts: `.vtt`, `.srt`

**Chunking Strategies:**

| Strategy | Description | Best For |
|----------|-------------|----------|
| `auto` | Automatically selects based on file type | Most use cases (recommended) |
| `hierarchical` | Structure-aware using Docling | DOCX, PDF, PPTX with headings |
| `markdown` | Markdown-aware splitting | Markdown files |
| `recursive` | Recursive text splitting | Plain text |
| `semantic` | Semantic boundary detection | Long-form content |
| `transcript` | Timestamp-aware splitting | VTT, SRT transcripts |

**Example Request:**
```bash
curl -X POST "https://api.stache.example.com/api/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf" \
  -F "chunking_strategy=auto" \
  -F "namespace=reports/2025" \
  -F 'metadata={"author": "John Doe", "department": "Engineering"}'
```

**Response:**
```json
{
  "success": true,
  "filename": "report.pdf",
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunks_created": 42,
  "chunking_strategy": "hierarchical",
  "namespace": "reports/2025"
}
```

---

#### `POST /api/upload/batch`
Upload multiple documents at once.

**Request:** Multipart form data

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `files` | file[] | Yes | - | List of files to upload |
| `chunking_strategy` | string | No | "auto" | Chunking strategy for all files |
| `namespace` | string | No | "default" | Target namespace for all files |
| `metadata` | string | No | null | JSON string of metadata to apply to all files |
| `prepend_metadata` | string | No | null | Comma-separated metadata keys |
| `skip_errors` | boolean | No | true | If true, continue on errors; if false, stop on first error |

**Example Request:**
```bash
curl -X POST "https://api.stache.example.com/api/upload/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@file1.pdf" \
  -F "files=@file2.docx" \
  -F "files=@file3.md" \
  -F "chunking_strategy=auto" \
  -F "namespace=project/docs" \
  -F 'metadata={"project": "alpha"}' \
  -F "skip_errors=true"
```

**Response:**
```json
{
  "success": true,
  "message": "Uploaded 3/3 files successfully",
  "results": [
    {
      "filename": "file1.pdf",
      "success": true,
      "chunks_created": 25,
      "doc_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    {
      "filename": "file2.docx",
      "success": true,
      "chunks_created": 18,
      "doc_id": "660e8400-e29b-41d4-a716-446655440001"
    },
    {
      "filename": "file3.md",
      "success": false,
      "error": "Unsupported file format"
    }
  ],
  "total_files": 3,
  "successful": 2,
  "failed": 1,
  "total_chunks": 43,
  "namespace": "project/docs"
}
```

---

### Capture

#### `POST /api/capture`
Capture a quick thought or note.

**Request Body:**
```json
{
  "text": "Meeting notes: Discussed RAG architecture improvements...",
  "metadata": {
    "source": "meeting",
    "date": "2025-01-10",
    "attendees": ["Alice", "Bob"]
  },
  "chunking_strategy": "recursive",
  "namespace": "notes/meetings",
  "prepend_metadata": ["source", "date"]
}
```

**Parameters:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `text` | string | Yes | - | Text content to capture |
| `metadata` | object | No | {} | Additional metadata |
| `chunking_strategy` | string | No | "recursive" | Chunking strategy |
| `namespace` | string | No | "default" | Target namespace |
| `prepend_metadata` | string[] | No | null | Metadata keys to prepend to chunks for better search |

**Response:**
```json
{
  "success": true,
  "message": "Thought captured successfully",
  "doc_id": "770e8400-e29b-41d4-a716-446655440002",
  "chunks_created": 3,
  "namespace": "notes/meetings"
}
```

---

### Documents

#### `GET /api/documents`
List all documents in the knowledge base.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `namespace` | string | null | Filter by namespace |
| `extension` | string | null | Filter by file extension (e.g., "pdf", "txt") |
| `orphaned` | boolean | false | Show only chunks without doc_id (legacy data, Qdrant only) |
| `use_summaries` | boolean | true | Use fast summary-based listing |
| `limit` | integer | 100 | Maximum documents to return (1-1000) |
| `next_key` | string | null | Pagination token from previous response |

**Example Request:**
```bash
curl "https://api.stache.example.com/api/documents?namespace=reports&extension=pdf&limit=50"
```

**Response:**
```json
{
  "documents": [
    {
      "doc_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "report.pdf",
      "namespace": "reports",
      "chunk_count": 42,
      "created_at": "2025-01-10T12:00:00Z",
      "headings": ["Introduction", "Chapter 1", "Conclusion"]
    }
  ],
  "count": 1,
  "source": "document_index",
  "next_key": "eyJkb2NfaWQiOiAiLi4uIn0="
}
```

---

#### `GET /api/documents/discover`
Semantic discovery of documents by topic or concept.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Semantic search query (e.g., "documents about leadership") |
| `namespace` | string | No | Optional namespace filter (supports wildcards like "mba/*") |
| `top_k` | integer | No | Number of documents to return (1-50, default 10) |

**Example Request:**
```bash
curl "https://api.stache.example.com/api/documents/discover?query=leadership%20strategies&namespace=books&top_k=5"
```

**Response:**
```json
{
  "query": "leadership strategies",
  "documents": [
    {
      "doc_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "leadership-guide.pdf",
      "namespace": "books",
      "headings": ["Chapter 1: Vision", "Chapter 2: Communication"],
      "chunk_count": 85,
      "created_at": "2025-01-08T10:30:00Z",
      "score": 0.92,
      "summary_preview": "This guide covers essential leadership strategies including vision setting, effective communication..."
    }
  ],
  "count": 5
}
```

---

#### `GET /api/documents/id/{doc_id}`
Get document by ID.

**Path Parameters:**
- `doc_id` (string, required): Document UUID

**Query Parameters:**
- `namespace` (string, default: "default"): Namespace containing the document

**Example Request:**
```bash
curl "https://api.stache.example.com/api/documents/id/550e8400-e29b-41d4-a716-446655440000?namespace=reports"
```

**Response:**
```json
{
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "report.pdf",
  "namespace": "reports",
  "chunk_count": 42,
  "created_at": "2025-01-10T12:00:00Z",
  "summary": "This document discusses...",
  "headings": ["Introduction", "Chapter 1", "Conclusion"],
  "metadata": {
    "author": "John Doe",
    "department": "Engineering"
  }
}
```

**Error Response (404):**
```json
{
  "detail": "Document not found: 550e8400-e29b-41d4-a716-446655440000"
}
```

---

#### `DELETE /api/documents/id/{doc_id}`
Delete document by ID.

**Path Parameters:**
- `doc_id` (string, required): Document UUID to delete

**Query Parameters:**
- `namespace` (string, default: "default"): Namespace containing the document

**Example Request:**
```bash
curl -X DELETE "https://api.stache.example.com/api/documents/id/550e8400-e29b-41d4-a716-446655440000?namespace=reports"
```

**Response:**
```json
{
  "success": true,
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "namespace": "reports",
  "chunks_deleted": 42
}
```

---

#### `DELETE /api/documents`
Delete document by filename.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Filename to delete |
| `namespace` | string | No | Optional namespace filter |

**Example Request:**
```bash
curl -X DELETE "https://api.stache.example.com/api/documents?filename=report.pdf&namespace=reports"
```

**Response:**
```json
{
  "success": true,
  "filename": "report.pdf",
  "namespace": "reports",
  "chunks_deleted": 42
}
```

---

#### `GET /api/documents/chunks`
Retrieve chunk text content by point IDs.

**Query Parameters:**
- `point_ids` (string, required): Comma-separated list of point IDs

**Example Request:**
```bash
curl "https://api.stache.example.com/api/documents/chunks?point_ids=abc123,def456,ghi789"
```

**Response:**
```json
{
  "chunks": [
    {
      "point_id": "abc123",
      "text": "This is the first chunk of text...",
      "filename": "report.pdf",
      "namespace": "reports",
      "chunk_index": 0,
      "doc_id": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2025-01-10T12:00:00Z"
    }
  ],
  "count": 3,
  "reconstructed_text": "This is the first chunk of text...\n\nThis is the second chunk...\n\n..."
}
```

---

#### `DELETE /api/documents/orphaned`
Delete orphaned chunks (chunks without doc_id). **Qdrant only.**

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | No | Delete orphaned chunks for specific filename |
| `all_orphaned` | boolean | No | Delete ALL orphaned chunks (use with caution) |

**Example Request:**
```bash
curl -X DELETE "https://api.stache.example.com/api/documents/orphaned?all_orphaned=true"
```

**Response:**
```json
{
  "success": true,
  "chunks_deleted": 127
}
```

**Error Response (501 - S3 Vectors):**
```json
{
  "detail": "This operation is only available for Qdrant. Orphaned chunks are legacy data from pre-UUID migrations. New S3 Vectors deployments don't have orphaned chunks."
}
```

---

#### `POST /api/documents/migrate-summaries`
Create document summary records for existing documents. **Qdrant only.**

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `namespace` | string | null | Only migrate documents in this namespace |
| `dry_run` | boolean | false | Show what would be migrated without making changes |

**Example Request:**
```bash
curl -X POST "https://api.stache.example.com/api/documents/migrate-summaries?dry_run=true"
```

**Response (Dry Run):**
```json
{
  "success": true,
  "dry_run": true,
  "existing_summaries": 42,
  "would_migrate": 15,
  "documents": [
    {
      "doc_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "report.pdf",
      "chunks": 42
    }
  ]
}
```

**Response (Actual Migration):**
```json
{
  "success": true,
  "existing_summaries": 42,
  "migrated": 15,
  "errors": []
}
```

---

### Namespaces

Namespaces organize your knowledge base into logical sections for multi-tenant or multi-project use cases.

#### `POST /api/namespaces`
Create a new namespace.

**Request Body:**
```json
{
  "id": "mba/finance/corporate-finance",
  "name": "Corporate Finance",
  "description": "Corporate finance materials and case studies",
  "parent_id": "mba/finance",
  "metadata": {
    "icon": "💰",
    "color": "#4CAF50"
  },
  "filter_keys": ["source", "date", "author", "topic"]
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique namespace ID (slug format, e.g., "mba/finance") |
| `name` | string | Yes | Display name |
| `description` | string | No | Description of what belongs in this namespace |
| `parent_id` | string | No | Parent namespace ID for hierarchy |
| `metadata` | object | No | Additional metadata (icon, color, tags, etc.) |
| `filter_keys` | string[] | No | Valid metadata keys for filtering searches (max 50) |

**Response:**
```json
{
  "id": "mba/finance/corporate-finance",
  "name": "Corporate Finance",
  "description": "Corporate finance materials and case studies",
  "parent_id": "mba/finance",
  "metadata": {
    "icon": "💰",
    "color": "#4CAF50"
  },
  "filter_keys": ["source", "date", "author", "topic"],
  "created_at": "2025-01-10T12:00:00Z",
  "doc_count": 0,
  "chunk_count": 0
}
```

---

#### `GET /api/namespaces`
List all namespaces.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parent_id` | string | null | Filter by parent namespace |
| `include_children` | boolean | false | Include all descendants (flat list) |
| `include_stats` | boolean | true | Include document/chunk counts (slower) |

**Example Request:**
```bash
curl "https://api.stache.example.com/api/namespaces?parent_id=mba&include_stats=true"
```

**Response:**
```json
{
  "namespaces": [
    {
      "id": "mba/finance",
      "name": "Finance",
      "description": "Finance course materials",
      "parent_id": "mba",
      "metadata": {},
      "filter_keys": ["source", "date"],
      "created_at": "2025-01-10T10:00:00Z",
      "doc_count": 25,
      "chunk_count": 1250
    }
  ],
  "count": 1
}
```

---

#### `GET /api/namespaces/tree`
Get namespaces as a hierarchical tree.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root_id` | string | null | Get subtree starting from this namespace |
| `include_stats` | boolean | false | Include document/chunk counts (slower) |

**Example Request:**
```bash
curl "https://api.stache.example.com/api/namespaces/tree?root_id=mba&include_stats=true"
```

**Response:**
```json
{
  "tree": [
    {
      "id": "mba",
      "name": "MBA Program",
      "description": "MBA course materials",
      "parent_id": null,
      "doc_count": 150,
      "chunk_count": 7500,
      "children": [
        {
          "id": "mba/finance",
          "name": "Finance",
          "doc_count": 25,
          "chunk_count": 1250,
          "children": []
        }
      ]
    }
  ],
  "count": 1
}
```

---

#### `GET /api/namespaces/{namespace_id}`
Get a single namespace by ID.

**Path Parameters:**
- `namespace_id` (string, required): Namespace ID (path parameter, supports slashes)

**Example Request:**
```bash
curl "https://api.stache.example.com/api/namespaces/mba/finance"
```

**Response:**
```json
{
  "id": "mba/finance",
  "name": "Finance",
  "description": "Finance course materials",
  "parent_id": "mba",
  "metadata": {},
  "filter_keys": ["source", "date"],
  "created_at": "2025-01-10T10:00:00Z",
  "doc_count": 25,
  "chunk_count": 1250,
  "path": ["mba", "mba/finance"],
  "ancestors": [
    {
      "id": "mba",
      "name": "MBA Program"
    }
  ]
}
```

---

#### `PUT /api/namespaces/{namespace_id}`
Update a namespace.

**Path Parameters:**
- `namespace_id` (string, required): Namespace ID to update

**Request Body:**
```json
{
  "name": "Finance & Accounting",
  "description": "Updated description",
  "parent_id": "mba",
  "metadata": {
    "icon": "💵",
    "tags": ["finance", "accounting"]
  },
  "filter_keys": ["source", "date", "author"]
}
```

**Notes:**
- Only provided fields will be updated
- Metadata is merged with existing (not replaced)
- Set `parent_id` to empty string `""` to make it a root namespace
- `filter_keys` replaces existing list entirely (not merged)

**Response:**
```json
{
  "id": "mba/finance",
  "name": "Finance & Accounting",
  "description": "Updated description",
  "parent_id": "mba",
  "metadata": {
    "icon": "💵",
    "tags": ["finance", "accounting"]
  },
  "filter_keys": ["source", "date", "author"],
  "doc_count": 25,
  "chunk_count": 1250
}
```

---

#### `DELETE /api/namespaces/{namespace_id}`
Delete a namespace.

**Path Parameters:**
- `namespace_id` (string, required): Namespace ID to delete

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cascade` | boolean | false | Delete child namespaces too |
| `delete_documents` | boolean | false | Also delete all documents from vector DB (DANGEROUS!) |

**Example Request:**
```bash
curl -X DELETE "https://api.stache.example.com/api/namespaces/mba/finance?cascade=true&delete_documents=true"
```

**Response:**
```json
{
  "success": true,
  "namespace_id": "mba/finance",
  "cascade": true,
  "documents_deleted": true,
  "chunks_deleted": 1250
}
```

**Error (namespace has children, cascade=false):**
```json
{
  "detail": "Cannot delete namespace with children. Use cascade=true to force deletion."
}
```

---

#### `GET /api/namespaces/{namespace_id}/documents`
List all documents in a namespace.

**Path Parameters:**
- `namespace_id` (string, required): Namespace ID

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum documents to return |
| `offset` | integer | 0 | Pagination offset |

**Example Request:**
```bash
curl "https://api.stache.example.com/api/namespaces/mba/finance/documents?limit=50&offset=0"
```

**Response:**
```json
{
  "namespace": "mba/finance",
  "documents": [
    {
      "doc_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "corporate-finance.pdf",
      "total_chunks": 85,
      "created_at": "2025-01-10T12:00:00Z"
    }
  ],
  "count": 1,
  "total": 25,
  "offset": 0,
  "limit": 50
}
```

---

### Pending Queue

The pending queue allows reviewing OCR'd documents before uploading to the knowledge base.

#### `GET /api/pending`
List all pending items in the queue.

**Response:**
```json
[
  {
    "id": "abc123",
    "original_filename": "scanned-doc.pdf",
    "suggested_filename": "meeting-notes-jan-2025",
    "suggested_namespace": "meetings",
    "extracted_text": "Meeting Notes\n\nDate: January 10, 2025...",
    "full_text_length": 1250,
    "created_at": "2025-01-10T12:00:00Z"
  }
]
```

---

#### `GET /api/pending/{item_id}`
Get a specific pending item.

**Path Parameters:**
- `item_id` (string, required): Pending item ID

**Response:**
```json
{
  "id": "abc123",
  "original_filename": "scanned-doc.pdf",
  "suggested_filename": "meeting-notes-jan-2025",
  "suggested_namespace": "meetings",
  "extracted_text": "Meeting Notes\n\nDate: January 10, 2025...",
  "full_text_length": 1250,
  "created_at": "2025-01-10T12:00:00Z"
}
```

---

#### `GET /api/pending/{item_id}/thumbnail`
Get the thumbnail image for a pending item.

**Path Parameters:**
- `item_id` (string, required): Pending item ID

**Response:** JPEG image (binary)

---

#### `GET /api/pending/{item_id}/pdf`
Get the PDF file for a pending item.

**Path Parameters:**
- `item_id` (string, required): Pending item ID

**Response:** PDF file (binary)

---

#### `POST /api/pending/{item_id}/approve`
Approve a pending item and upload to stache.

**Path Parameters:**
- `item_id` (string, required): Pending item ID

**Request Body:**
```json
{
  "filename": "meeting-notes-jan-2025",
  "namespace": "meetings/2025",
  "metadata": {
    "date": "2025-01-10",
    "attendees": ["Alice", "Bob"]
  },
  "chunking_strategy": "recursive",
  "prepend_metadata": ["date"]
}
```

**Response:**
```json
{
  "success": true,
  "filename": "meeting-notes-jan-2025",
  "namespace": "meetings/2025",
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunks_created": 15
}
```

---

#### `DELETE /api/pending/{item_id}`
Delete a pending item without uploading.

**Path Parameters:**
- `item_id` (string, required): Pending item ID

**Response:**
```json
{
  "success": true,
  "deleted": ["abc123.json", "abc123.pdf", "abc123.jpg"]
}
```

---

### Insights

Insights are user notes with semantic search capability.

#### `POST /api/insights`
Create a new insight.

**Request Body:**
```json
{
  "content": "Key insight: RAG systems benefit from hierarchical chunking strategies that preserve document structure.",
  "namespace": "notes/insights",
  "tags": ["rag", "chunking", "best-practices"]
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | Yes | Content of the insight (min length: 1) |
| `namespace` | string | Yes | Namespace for organizing insights |
| `tags` | string[] | No | Optional tags for categorization |

**Response:**
```json
{
  "success": true,
  "message": "Insight created successfully",
  "id": "insight_770e8400-e29b-41d4-a716-446655440003",
  "namespace": "notes/insights"
}
```

---

#### `GET /api/insights/search`
Search insights using semantic search.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (min length: 1) |
| `namespace` | string | Yes | Namespace to search within |
| `top_k` | integer | No | Maximum results to return (1-100, default 10) |

**Example Request:**
```bash
curl "https://api.stache.example.com/api/insights/search?query=chunking+strategies&namespace=notes/insights&top_k=5"
```

**Response:**
```json
{
  "results": [
    {
      "id": "insight_770e8400-e29b-41d4-a716-446655440003",
      "content": "Key insight: RAG systems benefit from hierarchical chunking strategies...",
      "similarity_score": 0.94,
      "tags": ["rag", "chunking", "best-practices"]
    }
  ],
  "total": 5
}
```

---

#### `DELETE /api/insights/{insight_id}`
Delete an insight by ID.

**Path Parameters:**
- `insight_id` (string, required): Insight ID

**Query Parameters:**
- `namespace` (string, required): Namespace containing the insight

**Example Request:**
```bash
curl -X DELETE "https://api.stache.example.com/api/insights/insight_770e8400-e29b-41d4-a716-446655440003?namespace=notes/insights"
```

**Response:**
```json
{
  "success": true,
  "message": "Insight insight_770e8400-e29b-41d4-a716-446655440003 deleted successfully"
}
```

---

### Models

#### `GET /api/models`
List available LLM models for query synthesis.

**Response:**
```json
{
  "models": [
    {
      "id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
      "name": "Claude 3.5 Sonnet",
      "tier": "balanced",
      "description": "High intelligence at balanced speed and cost"
    },
    {
      "id": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
      "name": "Claude 3.5 Haiku",
      "tier": "fast",
      "description": "Fastest responses with good intelligence"
    },
    {
      "id": "us.anthropic.claude-3-opus-20240229-v1:0",
      "name": "Claude 3 Opus",
      "tier": "premium",
      "description": "Highest intelligence for complex tasks"
    }
  ],
  "grouped": {
    "fast": [...],
    "balanced": [...],
    "premium": [...]
  },
  "default": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
  "provider": "bedrock"
}
```

---

## Best Practices

### 1. Use Namespaces for Organization

Organize your knowledge base with hierarchical namespaces:

```
mba/
├── finance/
│   ├── corporate-finance/
│   └── valuation/
├── marketing/
└── operations/
```

**Benefits:**
- Multi-tenant isolation
- Project-based organization
- Access control (future feature)
- Better query scoping

### 2. Choose the Right Chunking Strategy

| Content Type | Recommended Strategy | Why |
|--------------|---------------------|-----|
| Structured documents (PDF, DOCX) | `auto` or `hierarchical` | Preserves headings and structure |
| Markdown files | `auto` or `markdown` | Respects markdown syntax |
| Transcripts | `auto` or `transcript` | Preserves timestamps |
| Plain text | `recursive` | General-purpose splitting |
| Long-form content | `semantic` | Better boundary detection |

### 3. Use Metadata Effectively

Add meaningful metadata during ingestion:

```json
{
  "source": "meeting",
  "date": "2025-01-10",
  "department": "engineering",
  "attendees": ["Alice", "Bob"],
  "priority": "high"
}
```

Then filter queries:
```json
{
  "query": "action items",
  "filter": {
    "department": "engineering",
    "priority": "high"
  }
}
```

### 4. Use prepend_metadata for Better Search

Embed important metadata into vectors for semantic search:

```json
{
  "text": "...",
  "metadata": {
    "speaker": "Dr. Anderson",
    "topic": "Leadership"
  },
  "prepend_metadata": ["speaker", "topic"]
}
```

This prepends metadata to chunks: `"Speaker: Dr. Anderson\nTopic: Leadership\n\n[chunk text]"`

### 5. Pagination for Large Result Sets

Use pagination for listing documents:

```bash
# First request
curl "/api/documents?limit=100"

# Response includes next_key
{
  "documents": [...],
  "next_key": "eyJkb2NfaWQiOi4uLn0="
}

# Second request
curl "/api/documents?limit=100&next_key=eyJkb2NfaWQiOi4uLn0="
```

### 6. Error Handling

Always handle errors gracefully:

```javascript
try {
  const response = await fetch('/api/query', {
    method: 'POST',
    body: JSON.stringify({ query: 'test' })
  });

  if (!response.ok) {
    const error = await response.json();
    console.error('API Error:', error.detail);
    // Handle 404, 500, 501 differently
  }

  const data = await response.json();
} catch (error) {
  console.error('Network Error:', error);
}
```

### 7. Provider-Specific Considerations

**S3 Vectors:**
- Summaries created automatically during ingestion
- No support for orphaned chunks (legacy feature)
- No full metadata scans (use document index instead)

**Qdrant:**
- Supports full collection scans
- Legacy orphaned chunk cleanup available
- Summary migration available for old data

### 8. Optimize Query Performance

**For faster queries:**
- Set `synthesize=false` to skip LLM synthesis
- Reduce `top_k` to minimum needed results
- Use specific namespace filtering
- Apply metadata filters early

**For better quality:**
- Enable `rerank=true` (default)
- Use `synthesize=true` for natural language answers
- Increase `top_k` for more context
- Use semantic discovery for topic exploration

### 9. Batch Operations

Use batch upload for multiple files:

```bash
# Efficient: Single request
curl -X POST "/api/upload/batch" \
  -F "files=@doc1.pdf" \
  -F "files=@doc2.pdf" \
  -F "files=@doc3.pdf"

# Inefficient: Multiple requests
for file in *.pdf; do
  curl -X POST "/api/upload" -F "file=@$file"
done
```

### 10. Security Best Practices

- Always use HTTPS in production
- Validate JWT tokens on API Gateway
- Use namespace-based isolation for multi-tenancy
- Never expose internal IDs or system paths
- Sanitize user-provided metadata
- Implement rate limiting (API Gateway)
- Monitor for unusual access patterns

---

## Rate Limits

Rate limits are enforced at the API Gateway level (when deployed on AWS):

| Tier | Requests/Second | Burst |
|------|----------------|-------|
| Default | 10 | 20 |
| Premium | 100 | 200 |

**Rate Limit Response (429):**
```json
{
  "message": "Too Many Requests"
}
```

---

## Versioning

The API follows semantic versioning. The current version is `0.1.0`.

**Breaking changes** will increment the major version (e.g., `0.x.x` → `1.0.0`).

**Future versions** may include:
- `/api/v2/` prefix for breaking changes
- Deprecated endpoints with sunset dates
- Migration guides

---

## Support

For issues, questions, or feature requests:
- GitHub Issues: [stache repository](https://github.com/your-org/stache)
- Documentation: `/docs/` directory
- Session Notes: `/claude-stache-files/sessions/`

---

**Last Updated:** 2025-01-10
**API Version:** 0.1.0
