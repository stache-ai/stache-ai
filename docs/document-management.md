# Document Management

Stache provides comprehensive document management capabilities across all interfaces: Web UI, CLI, MCP (Claude Desktop/Code), and Python API.

## Features

- **Browse documents** - List all documents with filtering by namespace
- **View details** - See filename, namespace, chunk count, creation date, metadata
- **Edit metadata** - Update filename, custom metadata (JSON), or document headings
- **Migrate namespaces** - Move documents between namespaces
- **Delete documents** - Remove documents and all associated chunks

## Interfaces

### Web UI (`/documents`)

**Access**: Navigate to `/documents` in the Stache web interface

**Features**:
- Table view with search and namespace filtering
- Edit modal with JSON metadata editor and validation
- Delete confirmation dialog
- Mobile-responsive design
- Pagination for large document collections

**Usage**:
1. Open `/documents` page
2. Filter by namespace or search by filename
3. Click ✏️ to edit metadata
4. Click 🗑️ to delete (with confirmation)

### CLI (`stache doc`)

**Commands**:
```bash
# List documents
stache doc list
stache doc list -n research --limit 100

# Get document details
stache doc get <doc_id> -n default

# Update metadata
stache doc update <doc_id> --filename "new-name.pdf"
stache doc update <doc_id> --new-namespace archive
stache doc update <doc_id> --metadata '{"author": "Jane", "year": 2026}'

# Delete document
stache doc delete <doc_id> -n default
stache doc delete <doc_id> -n default --yes  # Skip confirmation
```

**Options**:
- `-n, --namespace` - Namespace filter (default: "default")
- `--new-namespace` - Migrate to new namespace
- `--filename` - Update filename
- `--metadata` - Custom metadata as JSON (replaces existing)
- `--json` - Output as JSON
- `--yes, -y` - Skip confirmation prompts

### MCP Tools (Claude Desktop/Code)

**Available Tools**:
- `list_documents` - List documents with optional namespace filter
- `get_document` - Get document by ID
- `update_document` - Update filename, namespace, or custom metadata
- `delete_document` - Delete document by ID

**Example Usage**:
```
User: "List my research documents"
Claude: [Calls list_documents tool with namespace="research"]

User: "Rename document abc-123 to 'final-report.pdf'"
Claude: [Calls update_document with doc_id="abc-123", new_filename="final-report.pdf"]

User: "Move all finance documents to the archive namespace"
Claude: [Lists finance docs, then calls update_document for each with new_namespace="archive"]
```

### Python API

```python
from stache_tools import StacheAPI

with StacheAPI() as api:
    # List documents
    result = api.list_documents(namespace="research", limit=50)
    for doc in result["documents"]:
        print(f"{doc['filename']}: {doc['chunk_count']} chunks")

    # Get document details
    doc = api.get_document(doc_id="abc-123", namespace="default")
    print(doc["filename"], doc["metadata"])

    # Update document
    api.update_document(
        doc_id="abc-123",
        namespace="default",
        updates={
            "filename": "renamed.pdf",
            "metadata": {"author": "Jane Doe", "year": 2026}
        }
    )

    # Delete document
    result = api.delete_document(doc_id="abc-123", namespace="default")
    print(f"Deleted {result['chunks_deleted']} chunks")
```

## Metadata Update Behavior

### Partial Updates
Only fields you specify are updated. Omitted fields remain unchanged.

```bash
# Only updates filename - namespace and metadata unchanged
stache doc update <id> --filename "new.pdf"
```

### Custom Metadata Replacement
**Important**: The `metadata` field **replaces** the entire custom metadata dict, it does not merge.

**Example**:
```bash
# Document has: {"author": "John", "year": 2025}
stache doc update <id> --metadata '{"tags": ["new"]}'
# Result: {"tags": ["new"]} - author and year are GONE
```

**Workaround for Merge**:
```bash
# 1. Get current metadata
stache doc get <id> --json > doc.json

# 2. Edit doc.json to add/modify fields

# 3. Extract and update
jq -r '.metadata' doc.json > metadata.json
stache doc update <id> --metadata "$(cat metadata.json)"
```

### System Metadata Preserved
System metadata fields (prefixed with `_`) are always preserved:
- `_type` - Chunk type (document_chunk, document_summary)
- `_split` - Split index for auto-split chunks
- `_chunk_id` - Internal chunk identifier
- `text` - Chunk text content

These cannot be modified through document update APIs.

## Provider Support

All vector DB and document index providers support document metadata updates:

| Provider | Namespace Migration | Metadata Update | Batch Size |
|----------|---------------------|-----------------|------------|
| S3 Vectors | ✅ | ✅ | 500 |
| Qdrant | ✅ | ✅ | 1000 |
| Pinecone | ✅ | ✅ | 1000 |
| MongoDB | ✅ | ✅ | N/A |
| DynamoDB | ✅ | ✅ | N/A |

**Dual-Write Pattern**:
Document updates perform a dual-write:
1. Update vector DB (all chunk metadata)
2. Update document index (DynamoDB/MongoDB)

If the document index update fails after vectors succeed, the operation logs a warning and returns partial success. The user can retry to fix consistency.

## API Endpoints

### REST API

```http
# List documents
GET /api/documents?namespace=research&limit=50

# Get document by ID
GET /api/documents/id/{doc_id}?namespace=default

# Update document metadata
PATCH /api/documents/{doc_id}?current_namespace=default
Content-Type: application/json

{
  "filename": "new-name.pdf",
  "namespace": "archive",
  "metadata": {"author": "Jane", "year": 2026}
}

# Delete document
DELETE /api/documents/id/{doc_id}?namespace=default
```

**Response Format** (Update):
```json
{
  "success": true,
  "doc_id": "abc-123",
  "namespace": "archive",
  "updated_chunks": 42,
  "message": "Updated document abc-123 (42 chunks)"
}
```

## Common Use Cases

### Renaming Documents
```bash
stache doc update <id> --filename "corrected-name.pdf"
```

### Organizing with Namespaces
```bash
# Archive old documents
stache doc list -n default --json | \
  jq -r '.documents[] | select(.created_at < "2024-01-01") | .doc_id' | \
  xargs -I {} stache doc update {} --new-namespace archive
```

### Adding Metadata
```bash
# Tag documents by topic
stache doc update <id> --metadata '{"topic": "finance", "priority": "high"}'
```

### Bulk Operations
```python
from stache_tools import StacheAPI

with StacheAPI() as api:
    # Get all documents in namespace
    result = api.list_documents(namespace="research")

    # Update metadata for all
    for doc in result["documents"]:
        api.update_document(
            doc_id=doc["doc_id"],
            namespace="research",
            updates={"metadata": {"processed": True}}
        )
```

## Troubleshooting

### Document Not Found
Ensure you're specifying the correct namespace:
```bash
stache doc update <id> -n old-namespace --new-namespace new-namespace
```

### Invalid JSON Metadata
Use single quotes around JSON and double quotes inside:
```bash
stache doc update <id> --metadata '{"key": "value"}'
```

### Partial Update Failure
If vectors update but document index fails, check logs and retry:
```bash
stache doc update <id> --filename "name.pdf"  # Retry same operation
```

## Security

- All operations require authentication (Cognito JWT or OAuth)
- Namespace access is enforced by provider permissions
- Document IDs are UUIDs (not enumerable)
- Metadata validation prevents injection attacks
