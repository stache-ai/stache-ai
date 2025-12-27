# Stache MCP Tools

Stache is a personal knowledge base. Use these tools to search, browse, and add content.

## Available Tools

### search
Search the knowledge base with natural language queries.

```
search(query="how to calculate NPV", namespace="mba/finance", top_k=10)
```

- `query`: Natural language search query
- `namespace`: Optional - filter to specific namespace (e.g., "mba/finance")
- `top_k`: Number of results (default 20, max 50)
- `rerank`: Whether to rerank for relevance (default true)

### list_namespaces
List all namespaces in the knowledge base.

```
list_namespaces()
```

Returns namespaces with doc counts. Use this to understand what's in the knowledge base.

### list_documents
List documents, optionally filtered by namespace.

```
list_documents(namespace="mba", limit=50)
```

- `namespace`: Optional filter
- `limit`: Max documents (default 50, max 100)
- `next_key`: Pagination token from previous response

### get_document
Get details about a specific document.

```
get_document(doc_id="abc-123", namespace="default")
```

Returns filename, summary, headings, chunk count, and metadata.

### ingest_text
Add text content to the knowledge base.

```
ingest_text(
    text="Meeting notes from Q4 planning...",
    namespace="work/meetings",
    metadata={"date": "2025-01-15", "attendees": ["Alice", "Bob"]}
)
```

- `text`: Content to ingest (max 100KB)
- `namespace`: Target namespace (default "default")
- `metadata`: Optional dict of metadata

## Ingesting Documents

When the user wants to add content to Stache:

1. **For text/notes**: Use `ingest_text` directly with the content
2. **For files**: Read the file first, then use `ingest_text` with the content

### Example: Ingesting a file

```python
# 1. Read the file
content = read_file("/path/to/document.md")

# 2. Ingest with metadata
ingest_text(
    text=content,
    namespace="projects/myproject",
    metadata={
        "filename": "document.md",
        "source": "local file"
    }
)
```

### Example: Ingesting meeting notes

```python
ingest_text(
    text="""
    # Team Standup 2025-01-15

    ## Attendees
    - Alice, Bob, Carol

    ## Updates
    - Alice: Finished the API refactor
    - Bob: Working on frontend tests
    - Carol: Reviewing PRs

    ## Action Items
    - [ ] Alice to document the new endpoints
    - [ ] Bob to fix flaky test
    """,
    namespace="work/standups",
    metadata={
        "date": "2025-01-15",
        "type": "standup"
    }
)
```

## Namespaces

Namespaces organize content hierarchically:
- `default` - General content
- `work/meetings` - Work meeting notes
- `mba/finance` - MBA finance course materials
- `projects/stache` - Project-specific docs

Use `list_namespaces()` to see existing namespaces before ingesting.

## Best Practices

1. **Use descriptive namespaces** - Makes searching more targeted
2. **Add metadata** - Dates, sources, tags help with retrieval
3. **Chunk large content** - Split very long documents into logical sections
4. **Search before ingesting** - Avoid duplicates by checking if content exists
