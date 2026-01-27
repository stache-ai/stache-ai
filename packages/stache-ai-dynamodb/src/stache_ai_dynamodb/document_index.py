"""DynamoDB-backed document index provider"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError
import json
import base64
import uuid

from stache_ai.providers.base import DocumentIndexProvider
from . import sanitize_for_dynamodb

logger = logging.getLogger(__name__)

"""Document status values."""
DOC_STATUS_ACTIVE = "active"
DOC_STATUS_DELETING = "deleting"
DOC_STATUS_PURGING = "purging"
DOC_STATUS_PURGED = "purged"


class DynamoDBDocumentIndex(DocumentIndexProvider):
    """DynamoDB-backed document index

    Implements DocumentIndexProvider using DynamoDB for efficient metadata-only
    queries without requiring vector database access.

    Schema:
    Main Table Items:
    - PK: "DOC#{namespace}#{doc_id}", SK: "METADATA" - Document metadata
    - PK: "HASH#{namespace}#{content_hash}#{filename}", SK: "RESERVATION" - Hash-based identifier
    - PK: "SOURCE#{namespace}#{source_path}", SK: "RESERVATION" - Source path identifier
    - PK: "TRASH#{namespace}#{filename}#{deleted_at_ms}", SK: "ENTRY" - Unique trash entry
    - PK: "CLEANUP#{cleanup_job_id}", SK: "JOB" - Cleanup job for permanent deletion

    GSI1 (Trash Listing):
    - GSI1PK: "TRASH#{namespace}"
    - GSI1SK: "{deleted_at_iso}" (for sorting by recency)

    GSI Indexes:
    - GSI1PK: "NAMESPACE#{namespace}", GSI1SK: "CREATED#{timestamp}"
    - GSI2PK: "FILENAME#{namespace}#{filename}", GSI2SK: "CREATED#{timestamp}"
    """

    def __init__(self, settings):
        """Initialize DynamoDB document index

        Args:
            settings: Settings object with DynamoDB configuration

        Raises:
            ValueError: If table doesn't exist or is not ACTIVE
        """
        self.table_name = settings.dynamodb_documents_table
        self.aws_region = settings.aws_region
        self.client = boto3.client('dynamodb', region_name=self.aws_region)
        self.resource = boto3.resource('dynamodb', region_name=self.aws_region)
        self.table = self.resource.Table(self.table_name)

        # Validate table exists and is active
        self._ensure_table()
        logger.info(f"DynamoDB document index initialized: {self.table_name}")

    def _ensure_table(self):
        """Verify table exists and is ACTIVE

        Raises:
            ValueError: If table doesn't exist or is not ACTIVE
        """
        try:
            response = self.client.describe_table(TableName=self.table_name)
            status = response['Table']['TableStatus']
            if status != 'ACTIVE':
                raise ValueError(
                    f"DynamoDB table {self.table_name} is not ACTIVE (status: {status})"
                )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                raise ValueError(f"DynamoDB table {self.table_name} does not exist")
            raise

    def _make_pk(self, namespace: str, doc_id: str) -> str:
        """Create primary key

        Args:
            namespace: Document namespace
            doc_id: Document ID

        Returns:
            Primary key in format: DOC#{namespace}#{doc_id}
        """
        return f"DOC#{namespace}#{doc_id}"

    def _make_gsi1pk(self, namespace: str) -> str:
        """Create GSI1 partition key for namespace queries

        Args:
            namespace: Document namespace

        Returns:
            GSI1 partition key in format: NAMESPACE#{namespace}
        """
        return f"NAMESPACE#{namespace}"

    def _make_gsi1sk(self, timestamp: str) -> str:
        """Create GSI1 sort key using timestamp

        Args:
            timestamp: ISO 8601 timestamp string

        Returns:
            GSI1 sort key in format: CREATED#{timestamp}
        """
        return f"CREATED#{timestamp}"

    def _make_gsi2pk(self, namespace: str, filename: str, source_path: str | None = None) -> str:
        """Create GSI2 partition key for source path/filename lookups

        Uses source_path for uniqueness when available (CLI ingestion),
        falls back to filename for web uploads.

        Args:
            namespace: Document namespace
            filename: Document filename (display name)
            source_path: Optional source path from CLI ingestion

        Returns:
            GSI2 partition key in format: FILENAME#{namespace}#{source_path_or_filename}
        """
        identifier = source_path if source_path else filename
        return f"FILENAME#{namespace}#{identifier}"

    def create_document(
        self,
        doc_id: str,
        filename: str,
        namespace: str,
        chunk_ids: List[str],
        summary: Optional[str] = None,
        summary_embedding_id: Optional[str] = None,
        headings: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        file_type: Optional[str] = None,
        file_size: Optional[int] = None,
        source_path: Optional[str] = None,
        content_hash: Optional[str] = None,
        chunk_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create document index entry with active status by default

        Args:
            doc_id: Unique document identifier (typically UUID)
            filename: Original filename of the document (display name)
            namespace: Namespace/partition for the document
            chunk_ids: List of chunk IDs from vector database
            summary: Optional AI-generated summary of document
            summary_embedding_id: ID of the summary embedding in vector DB
            headings: Optional list of extracted headings from document
            metadata: Optional custom metadata dictionary
            file_type: Optional file type (pdf, epub, txt, md, etc.)
            file_size: Optional original file size in bytes
            source_path: Optional source path for deduplication (CLI ingestion)
            content_hash: Optional SHA-256 hash of content for deduplication
            chunk_count: Optional explicit chunk count (defaults to len(chunk_ids))

        Returns:
            Dictionary containing the created document record

        Raises:
            ClientError: If DynamoDB operation fails
        """
        created_at = datetime.now(timezone.utc).isoformat()
        actual_chunk_count = chunk_count if chunk_count is not None else len(chunk_ids)

        item = {
            "PK": self._make_pk(namespace, doc_id),
            "SK": "METADATA",
            "GSI1PK": self._make_gsi1pk(namespace),
            "GSI1SK": self._make_gsi1sk(created_at),
            "GSI2PK": self._make_gsi2pk(namespace, filename, source_path),
            "GSI2SK": self._make_gsi1sk(created_at),
            "doc_id": doc_id,
            "filename": filename,
            "namespace": namespace,
            "chunk_count": actual_chunk_count,
            "created_at": created_at,
            "chunk_ids": chunk_ids,
            "status": DOC_STATUS_ACTIVE,
        }

        # Deduplication fields - store for future lookups
        if source_path:
            item["source_path"] = source_path
        if content_hash:
            item["content_hash"] = content_hash

        # Optional fields - only include if provided
        if summary:
            item["summary"] = summary
        if summary_embedding_id:
            item["summary_embedding_id"] = summary_embedding_id
        if headings:
            item["headings"] = headings
        if metadata:
            item["metadata"] = metadata
        if file_type:
            item["file_type"] = file_type
        if file_size is not None:
            item["file_size"] = file_size

        try:
            # Sanitize floats to Decimal for DynamoDB compatibility
            sanitized_item = sanitize_for_dynamodb(item)
            self.table.put_item(Item=sanitized_item)
            logger.info(f"Created document index: {doc_id} in namespace {namespace}")
            return item
        except ClientError as e:
            logger.error(f"Failed to create document index for {doc_id}: {e}")
            raise

    def get_document(
        self,
        doc_id: str,
        namespace: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a document by ID

        Args:
            doc_id: Document identifier to retrieve
            namespace: Namespace for the document (required for this implementation)

        Returns:
            Dictionary with document metadata if found, None otherwise

        Raises:
            ValueError: If namespace is not provided
            ClientError: If DynamoDB operation fails
        """
        if not namespace:
            raise ValueError("Namespace is required for get_document in DynamoDB provider")

        try:
            response = self.table.get_item(
                Key={
                    "PK": self._make_pk(namespace, doc_id),
                    "SK": "METADATA"
                }
            )
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Failed to get document {doc_id}: {e}")
            raise

    def list_documents(
        self,
        namespace: Optional[str] = None,
        limit: int = 100,
        last_evaluated_key: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """List documents with pagination support

        Args:
            namespace: Optional namespace to filter by (None = all namespaces)
            limit: Maximum number of documents to return (default 100)
            last_evaluated_key: Pagination token from previous response

        Returns:
            Dictionary with structure:
            {
                "documents": List[Dict[str, Any]],
                "next_key": Optional[Dict[str, Any]]
            }

        Raises:
            ClientError: If DynamoDB operation fails
        """
        if namespace:
            # Query by namespace using GSI1 - most recent first
            query_params = {
                "IndexName": "GSI1",
                "KeyConditionExpression": "GSI1PK = :pk",
                "FilterExpression": "#status = :active",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":pk": self._make_gsi1pk(namespace),
                    ":active": DOC_STATUS_ACTIVE
                },
                "Limit": limit,
                "ScanIndexForward": False  # Most recent first
            }

            if last_evaluated_key:
                query_params["ExclusiveStartKey"] = last_evaluated_key

            try:
                response = self.table.query(**query_params)
                return {
                    "documents": response.get('Items', []),
                    "next_key": response.get('LastEvaluatedKey')
                }
            except ClientError as e:
                logger.error(f"Failed to list documents in namespace {namespace}: {e}")
                raise
        else:
            # Scan all documents (expensive operation, use sparingly)
            scan_params = {
                "FilterExpression": "#status = :active",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {":active": DOC_STATUS_ACTIVE},
                "Limit": limit
            }

            if last_evaluated_key:
                scan_params["ExclusiveStartKey"] = last_evaluated_key

            try:
                response = self.table.scan(**scan_params)
                return {
                    "documents": response.get('Items', []),
                    "next_key": response.get('LastEvaluatedKey')
                }
            except ClientError as e:
                logger.error(f"Failed to scan all documents: {e}")
                raise

    def delete_document(
        self,
        doc_id: str,
        namespace: Optional[str] = None
    ) -> bool:
        """Delete a document index entry

        Args:
            doc_id: Document identifier to delete
            namespace: Namespace for the document (required for this implementation)

        Returns:
            True if document was deleted, False if not found

        Raises:
            ValueError: If namespace is not provided
            ClientError: If DynamoDB operation fails
        """
        if not namespace:
            raise ValueError("Namespace is required for delete_document in DynamoDB provider")

        try:
            self.table.delete_item(
                Key={
                    "PK": self._make_pk(namespace, doc_id),
                    "SK": "METADATA"
                }
            )
            logger.info(f"Deleted document index: {doc_id} from namespace {namespace}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            raise

    def update_document_summary(
        self,
        doc_id: str,
        summary: str,
        summary_embedding_id: str,
        namespace: Optional[str] = None
    ) -> bool:
        """Update the summary and summary embedding ID for a document

        Args:
            doc_id: Document identifier to update
            summary: New summary text
            summary_embedding_id: ID of the summary embedding in vector database
            namespace: Namespace for the document (required for this implementation)

        Returns:
            True if update was successful, False if document not found

        Raises:
            ValueError: If namespace is not provided
            ClientError: If DynamoDB operation fails
        """
        if not namespace:
            raise ValueError("Namespace is required for update_document_summary in DynamoDB provider")

        try:
            self.table.update_item(
                Key={
                    "PK": self._make_pk(namespace, doc_id),
                    "SK": "METADATA"
                },
                UpdateExpression="SET summary = :summary, summary_embedding_id = :sid",
                ExpressionAttributeValues={
                    ":summary": summary,
                    ":sid": summary_embedding_id
                }
            )
            logger.info(f"Updated summary for document {doc_id} in namespace {namespace}")
            return True
        except ClientError as e:
            logger.error(f"Failed to update summary for {doc_id}: {e}")
            raise

    def update_document_metadata(
        self,
        doc_id: str,
        namespace: str,
        updates: dict[str, Any]
    ) -> bool:
        """Update document metadata atomically in DynamoDB

        Handles namespace migration by:
        1. Reading current document
        2. Deleting old item (PK includes namespace)
        3. Writing new item with updated fields

        For other updates, uses UpdateExpression for atomic in-place updates.
        """
        allowed_fields = {"namespace", "filename", "metadata", "headings"}
        invalid = set(updates.keys()) - allowed_fields
        if invalid:
            raise ValueError(f"Cannot update fields: {invalid}. Allowed: {allowed_fields}")

        # Special case: namespace migration requires PK change (delete + recreate)
        if "namespace" in updates:
            return self._migrate_namespace(doc_id, namespace, updates)

        # Standard update: use UpdateExpression for atomic updates
        return self._update_in_place(doc_id, namespace, updates)

    def _migrate_namespace(
        self,
        doc_id: str,
        old_namespace: str,
        updates: dict[str, Any]
    ) -> bool:
        """Migrate document to new namespace using atomic DynamoDB transaction.

        Uses low-level client API throughout to avoid serialization mismatches
        between high-level resource (deserialized) and transaction (serialized).

        Handles retry scenarios where document may already be in target namespace.
        """
        new_namespace = updates["namespace"]

        # Same namespace - nothing to do
        if old_namespace == new_namespace:
            logger.info(f"Document {doc_id} already in namespace {new_namespace}")
            return True

        try:
            old_pk = self._make_pk(old_namespace, doc_id)
            new_pk = self._make_pk(new_namespace, doc_id)

            # 1. Get current document using LOW-LEVEL client (returns DynamoDB format)
            response = self.client.get_item(
                TableName=self.table_name,
                Key={"PK": {"S": old_pk}, "SK": {"S": "METADATA"}}
            )

            if "Item" not in response:
                # Check if already migrated (retry scenario)
                new_response = self.client.get_item(
                    TableName=self.table_name,
                    Key={"PK": {"S": new_pk}, "SK": {"S": "METADATA"}}
                )
                if "Item" in new_response:
                    logger.info(f"Document {doc_id} already in target namespace {new_namespace} (idempotent)")
                    return True
                logger.warning(f"Document {doc_id} not found in namespace {old_namespace} or {new_namespace}")
                return False

            # Item is already in DynamoDB format (e.g., {"S": "value"})
            item = response["Item"]

            # 2. Build new item by updating specific fields in DynamoDB format
            # Get filename from updates or existing item
            if "filename" in updates:
                filename = updates["filename"]
            else:
                filename = item.get("filename", {}).get("S", "unknown")

            # Create new item with updated keys (already in DynamoDB format)
            new_item = {
                **item,
                "PK": {"S": new_pk},
                "namespace": {"S": new_namespace},
                "GSI1PK": {"S": f"NAMESPACE#{new_namespace}"},
                "GSI2PK": {"S": f"FILENAME#{new_namespace}#{filename}"},
                "filename": {"S": filename},
            }

            # Handle optional metadata update (need to serialize new values)
            if "metadata" in updates:
                from boto3.dynamodb.types import TypeSerializer
                serializer = TypeSerializer()
                new_item["metadata"] = serializer.serialize(updates["metadata"])

            # Handle optional headings update
            if "headings" in updates:
                from boto3.dynamodb.types import TypeSerializer
                serializer = TypeSerializer()
                new_item["headings"] = serializer.serialize(updates["headings"])

            # 3. Use atomic transaction: delete old + put new
            logger.info(f"Migrating {doc_id}: {old_namespace} -> {new_namespace}")

            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Delete": {
                            "TableName": self.table_name,
                            "Key": {"PK": {"S": old_pk}, "SK": {"S": "METADATA"}}
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": new_item
                        }
                    }
                ]
            )

            logger.info(f"Migrated document {doc_id} from {old_namespace} to {new_namespace}")
            return True

        except ClientError as e:
            logger.error(f"Failed to migrate document {doc_id}: {e}")
            raise

    def _update_in_place(
        self,
        doc_id: str,
        namespace: str,
        updates: dict[str, Any]
    ) -> bool:
        """Update document fields in-place using UpdateExpression"""
        update_parts = []
        attr_values = {}

        if "filename" in updates:
            update_parts.append("filename = :filename")
            update_parts.append("GSI2PK = :gsi2pk")  # Must update GSI2PK too
            attr_values[":filename"] = updates["filename"]
            attr_values[":gsi2pk"] = f"FILENAME#{namespace}#{updates['filename']}"

        if "metadata" in updates:
            update_parts.append("metadata = :metadata")
            attr_values[":metadata"] = updates["metadata"]

        if "headings" in updates:
            update_parts.append("headings = :headings")
            attr_values[":headings"] = updates["headings"]

        if not update_parts:
            raise ValueError("No valid non-namespace updates provided")

        try:
            self.table.update_item(
                Key={"PK": self._make_pk(namespace, doc_id), "SK": "METADATA"},
                UpdateExpression=f"SET {', '.join(update_parts)}",
                ExpressionAttributeValues=attr_values
            )
            logger.info(f"Updated metadata for document {doc_id} in namespace {namespace}")
            return True

        except ClientError as e:
            logger.error(f"Failed to update document {doc_id}: {e}")
            raise

    def get_chunk_ids(
        self,
        doc_id: str,
        namespace: Optional[str] = None
    ) -> List[str]:
        """Retrieve all chunk IDs for a document

        Args:
            doc_id: Document identifier
            namespace: Namespace for the document

        Returns:
            List of chunk IDs from the vector database
        """
        try:
            doc = self.get_document(doc_id, namespace)
            if doc:
                return doc.get('chunk_ids', [])
            return []
        except (ValueError, ClientError):
            logger.warning(f"Could not retrieve chunk IDs for {doc_id}")
            return []

    def document_exists(
        self,
        filename: str,
        namespace: str
    ) -> bool:
        """Check if a document with the given filename already exists in namespace

        Args:
            filename: Filename to check
            namespace: Namespace to search in

        Returns:
            True if a document with this filename exists in the namespace
        """
        try:
            response = self.table.query(
                IndexName="GSI2",
                KeyConditionExpression="GSI2PK = :pk",
                ExpressionAttributeValues={
                    ":pk": self._make_gsi2pk(namespace, filename)
                },
                Limit=1
            )
            return len(response.get('Items', [])) > 0
        except ClientError as e:
            logger.error(f"Failed to check document existence for {filename}: {e}")
            return False

    def get_document_by_source_path(
        self,
        namespace: str,
        source_path: str | None = None,
        filename: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Find active document by source_path or filename using GSI2.

        Used for deduplication: checks if document already exists at this path.
        Returns full document metadata including content_hash for version comparison.

        Args:
            namespace: Namespace to search in
            source_path: Source path from CLI ingestion (preferred identifier)
            filename: Fallback filename for web uploads

        Returns:
            Document metadata if found and active, None otherwise
        """
        identifier = source_path if source_path else filename
        if not identifier:
            return None

        try:
            response = self.table.query(
                IndexName="GSI2",
                KeyConditionExpression="GSI2PK = :pk",
                FilterExpression="#status = :active",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":pk": self._make_gsi2pk(namespace, filename or "", source_path),
                    ":active": DOC_STATUS_ACTIVE,
                },
                Limit=1
            )

            items = response.get('Items', [])
            if not items:
                return None

            item = items[0]
            return {
                "doc_id": item["doc_id"],
                "namespace": item["namespace"],
                "filename": item.get("filename"),
                "source_path": item.get("source_path"),
                "content_hash": item.get("content_hash"),
                "chunk_ids": item.get("chunk_ids", []),
                "created_at": item.get("created_at"),
            }

        except ClientError as e:
            logger.error(f"Failed to lookup document by source_path {identifier}: {e}")
            return None

    def count_by_namespace(self, namespace: str) -> dict[str, int]:
        """Get document and chunk counts for a namespace

        Uses GSI1 to efficiently query all documents in a namespace
        and sum their chunk counts.

        Args:
            namespace: Namespace to count documents for

        Returns:
            Dictionary with doc_count and chunk_count
        """
        try:
            doc_count = 0
            chunk_count = 0

            # Query GSI1 by namespace - paginate through all documents
            query_params = {
                "IndexName": "GSI1",
                "KeyConditionExpression": "GSI1PK = :pk",
                "ExpressionAttributeValues": {
                    ":pk": self._make_gsi1pk(namespace)
                },
                "ProjectionExpression": "chunk_count"  # Only fetch what we need
            }

            paginator = self.client.get_paginator('query')
            for page in paginator.paginate(
                TableName=self.table_name,
                **query_params
            ):
                for item in page.get('Items', []):
                    doc_count += 1
                    # DynamoDB returns chunk_count as {'N': '123'}
                    count_value = item.get('chunk_count', {}).get('N', '0')
                    chunk_count += int(count_value)

            return {"doc_count": doc_count, "chunk_count": chunk_count}
        except ClientError as e:
            logger.error(f"Failed to count documents in namespace {namespace}: {e}")
            return {"doc_count": 0, "chunk_count": 0}

    def get_name(self) -> str:
        """Get the provider name

        Returns:
            Name of the document index provider
        """
        return "dynamodb-document-index"

    def _compute_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Compute document identifier based on available metadata.

        Returns: (identifier_pk, identifier_type)
        """
        if source_path and not source_path.startswith("/tmp"):
            return f"SOURCE#{namespace}#{source_path}", "source_path"
        else:
            return f"HASH#{namespace}#{content_hash}#{filename}", "fingerprint"

    def reserve_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        doc_id: str,
        source_path: Optional[str] = None,
        file_size: Optional[int] = None,
        file_modified_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Atomically reserve identifier using DynamoDB conditional put.

        Args:
            content_hash: Content hash of the file
            filename: Filename of the document
            namespace: Namespace for the document
            doc_id: Document ID to associate with the identifier
            source_path: Optional source path for SOURCE-based identifiers
            file_size: Optional file size in bytes
            file_modified_at: Optional file modification timestamp
            metadata: Optional additional metadata

        Returns:
            True if reservation was successful, False if identifier already exists
        """
        identifier_pk, identifier_type = self._compute_identifier(
            content_hash, filename, namespace, source_path
        )

        item = {
            "PK": identifier_pk,
            "SK": "RESERVATION",
            "identifier_type": identifier_type,
            "doc_id": doc_id,
            "namespace": namespace,
            "content_hash": content_hash,
            "filename": filename,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }

        if source_path:
            item["source_path"] = source_path
        if file_size is not None:
            item["file_size"] = file_size
        if file_modified_at:
            item["file_modified_at"] = file_modified_at
        if metadata:
            item.update(metadata)

        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)"
            )
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False

    def get_document_by_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve document by identifier (strongly consistent read).

        Args:
            content_hash: Content hash of the file
            filename: Filename of the document
            namespace: Namespace for the document
            source_path: Optional source path for SOURCE-based identifiers

        Returns:
            Document metadata if found and complete, None otherwise
        """
        identifier_pk, _ = self._compute_identifier(
            content_hash, filename, namespace, source_path
        )

        response = self.table.get_item(
            Key={
                "PK": identifier_pk,
                "SK": "RESERVATION"
            },
            ConsistentRead=True
        )

        item = response.get("Item")
        # Treat missing status as "complete" for legacy documents (backward compatibility)
        if not item or item.get("status", "complete") != "complete":
            return None

        return {
            "doc_id": item["doc_id"],
            "namespace": item["namespace"],
            "identifier_type": item["identifier_type"],
            "content_hash": item["content_hash"],
            "filename": item["filename"],
            "source_path": item.get("source_path"),
            "file_size": item.get("file_size"),
            "file_modified_at": item.get("file_modified_at"),
            "ingested_at": item.get("ingested_at"),
            "version": item.get("version", 1),
        }

    def complete_identifier_reservation(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        doc_id: str,
        chunk_count: int,
        source_path: Optional[str] = None
    ) -> None:
        """Mark identifier reservation as complete.

        Args:
            content_hash: Content hash of the file
            filename: Filename of the document
            namespace: Namespace for the document
            doc_id: Document ID
            chunk_count: Number of chunks ingested
            source_path: Optional source path for SOURCE-based identifiers
        """
        identifier_pk, _ = self._compute_identifier(
            content_hash, filename, namespace, source_path
        )

        self.table.update_item(
            Key={
                "PK": identifier_pk,
                "SK": "RESERVATION"
            },
            UpdateExpression="SET #status = :status, chunk_count = :count, ingested_at = :ts",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "complete",
                ":count": chunk_count,
                ":ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    def release_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: Optional[str] = None
    ) -> None:
        """Release identifier reservation on failure.

        Args:
            content_hash: Content hash of the file
            filename: Filename of the document
            namespace: Namespace for the document
            source_path: Optional source path for SOURCE-based identifiers
        """
        identifier_pk, _ = self._compute_identifier(
            content_hash, filename, namespace, source_path
        )

        self.table.delete_item(
            Key={
                "PK": identifier_pk,
                "SK": "RESERVATION"
            }
        )

    def soft_delete_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_by: Optional[str] = None,
        delete_reason: str = "user_initiated"
    ) -> Dict[str, Any]:
        """
        Soft delete using DynamoDB transaction (atomic).

        Uses transact_write_items to atomically:
        1. Update document status to "deleting"
        2. Create trash entry with unique PK

        Args:
            doc_id: Document ID to soft delete
            namespace: Document namespace
            deleted_by: Optional user ID who initiated the delete
            delete_reason: Reason for deletion (default: user_initiated)

        Returns:
            Dictionary with deletion metadata
        """
        now = datetime.now(timezone.utc)
        deleted_at_ms = int(now.timestamp() * 1000)
        purge_after = now + timedelta(days=30)

        # Get document metadata first
        response = self.table.get_item(
            Key={
                "PK": f"DOC#{namespace}#{doc_id}",
                "SK": "METADATA"
            }
        )

        item = response.get("Item")
        if not item:
            raise ValueError(f"Document not found: {doc_id}")

        if item.get("status") == DOC_STATUS_DELETING:
            raise ValueError(f"Document already in trash: {doc_id}")

        if item.get("status") == DOC_STATUS_PURGING:
            raise ValueError(f"Document being permanently deleted: {doc_id}")

        if item.get("status") == DOC_STATUS_PURGED:
            raise ValueError(f"Document permanently deleted: {doc_id}")

        chunk_ids = item.get("chunk_ids", [])
        filename = item.get("filename", "unknown")

        # Build transaction items
        update_expr_parts = [
            "#status = :deleting",
            "deleted_at = :now",
            "purge_after = :purge_after"
        ]
        expr_values = {
            ":deleting": DOC_STATUS_DELETING,
            ":active": DOC_STATUS_ACTIVE,
            ":now": now.isoformat(),
            ":purge_after": purge_after.isoformat(),
        }

        if deleted_by:
            update_expr_parts.append("deleted_by = :deleted_by")
            expr_values[":deleted_by"] = deleted_by
        if delete_reason:
            update_expr_parts.append("delete_reason = :delete_reason")
            expr_values[":delete_reason"] = delete_reason

        # ATOMIC: Update doc + create trash entry in single transaction
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        # Update document status
                        "Update": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": {"S": f"DOC#{namespace}#{doc_id}"},
                                "SK": {"S": "METADATA"}
                            },
                            "UpdateExpression": "SET " + ", ".join(update_expr_parts),
                            "ConditionExpression": "#status = :active",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": {
                                k: {"S": v} if isinstance(v, str) else {"N": str(v)}
                                for k, v in expr_values.items()
                            }
                        }
                    },
                    {
                        # Create trash entry with unique PK (allows multiple deletions)
                        "Put": {
                            "TableName": self.table.name,
                            "Item": {
                                "PK": {"S": f"TRASH#{namespace}#{filename}#{deleted_at_ms}"},
                                "SK": {"S": "ENTRY"},
                                "doc_id": {"S": doc_id},
                                "namespace": {"S": namespace},
                                "filename": {"S": filename},
                                "deleted_at": {"S": now.isoformat()},
                                "deleted_at_ms": {"N": str(deleted_at_ms)},
                                "deleted_by": {"S": deleted_by} if deleted_by else {"NULL": True},
                                "delete_reason": {"S": delete_reason},
                                "chunk_count": {"N": str(len(chunk_ids))},
                                "purge_after": {"S": purge_after.isoformat()},
                                "GSI1PK": {"S": "TRASH"},
                                "GSI1SK": {"S": now.isoformat()},
                            }
                        }
                    }
                ]
            )
        except self.client.exceptions.TransactionCanceledException as e:
            # Check which condition failed
            reasons = e.response.get("CancellationReasons", [])
            if any("ConditionalCheckFailed" in str(r) for r in reasons):
                raise ValueError(f"Document status is not active (concurrent modification)")
            raise

        logger.info(
            "Document soft deleted",
            extra={
                "doc_id": doc_id,
                "namespace": namespace,
                "deleted_by": deleted_by,
                "deleted_at_ms": deleted_at_ms,
            }
        )

        return {
            "doc_id": doc_id,
            "namespace": namespace,
            "chunk_ids": chunk_ids,
            "filename": filename,
            "deleted_at": now.isoformat(),
            "deleted_at_ms": deleted_at_ms,
            "purge_after": purge_after.isoformat(),
        }

    def restore_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,
        restored_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Restore document from trash using DynamoDB transaction.

        Args:
            doc_id: Document ID to restore
            namespace: Document namespace
            deleted_at_ms: Identifies specific trash entry (supports multiple deletions)
            restored_by: Optional user ID who initiated the restore

        Returns:
            Dictionary with restoration metadata
        """
        now = datetime.now(timezone.utc)

        # Get document metadata
        response = self.table.get_item(
            Key={
                "PK": f"DOC#{namespace}#{doc_id}",
                "SK": "METADATA"
            }
        )

        item = response.get("Item")
        if not item:
            raise ValueError(f"Document not found: {doc_id}")

        current_status = item.get("status")
        if current_status not in (DOC_STATUS_DELETING, DOC_STATUS_PURGING):
            raise ValueError(f"Document not in trash: {doc_id} (status: {current_status})")

        # Check if recovering from purging (cleanup worker failure)
        is_recovery = current_status == DOC_STATUS_PURGING

        filename = item.get("filename", "unknown")
        chunk_ids = item.get("chunk_ids", [])  # For vector status restoration
        chunk_count = len(chunk_ids)

        # Build update expression
        update_expr_parts = [
            "#status = :active",
            "restored_at = :now"
        ]
        remove_parts = ["deleted_at", "purge_after"]

        if item.get("deleted_by"):
            remove_parts.append("deleted_by")
        if item.get("delete_reason"):
            remove_parts.append("delete_reason")

        # Clean up purge-related fields if recovering from purging status
        if is_recovery:
            if item.get("purge_started_at"):
                remove_parts.append("purge_started_at")
            if item.get("cleanup_job_id"):
                remove_parts.append("cleanup_job_id")

        expr_values = {
            ":active": DOC_STATUS_ACTIVE,
            ":deleting": DOC_STATUS_DELETING,
            ":now": now.isoformat(),
        }

        if restored_by:
            update_expr_parts.append("restored_by = :restored_by")
            expr_values[":restored_by"] = restored_by

        # ATOMIC: Update doc + delete trash entry in transaction
        # Allow restoring from both "deleting" (normal trash) and "purging" (cleanup failure recovery)
        condition_expr = "#status IN (:deleting, :purging)" if is_recovery else "#status = :deleting"

        # Add purging status to expression values if recovering
        if is_recovery:
            expr_values[":purging"] = DOC_STATUS_PURGING

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        # Update document status to active
                        "Update": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": {"S": f"DOC#{namespace}#{doc_id}"},
                                "SK": {"S": "METADATA"}
                            },
                            "UpdateExpression": (
                                f"SET {', '.join(update_expr_parts)} "
                                f"REMOVE {', '.join(remove_parts)}"
                            ),
                            "ConditionExpression": condition_expr,
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": {
                                k: {"S": v} for k, v in expr_values.items()
                            }
                        }
                    },
                    {
                        # Delete specific trash entry
                        "Delete": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": {"S": f"TRASH#{namespace}#{filename}#{deleted_at_ms}"},
                                "SK": {"S": "ENTRY"}
                            }
                        }
                    }
                ]
            )
        except self.client.exceptions.TransactionCanceledException as e:
            reasons = e.response.get("CancellationReasons", [])
            if any("ConditionalCheckFailed" in str(r) for r in reasons):
                raise ValueError(
                    f"Document status changed during restore (expected: {current_status}). "
                    "Please retry."
                )
            raise

        logger.info(
            "Document restored from trash",
            extra={
                "doc_id": doc_id,
                "namespace": namespace,
                "restored_by": restored_by,
                "deleted_at_ms": deleted_at_ms,
                "recovery_from_purging": is_recovery,
            }
        )

        result = {
            "doc_id": doc_id,
            "namespace": namespace,
            "status": DOC_STATUS_ACTIVE,
            "restored_at": now.isoformat(),
            "chunk_ids": chunk_ids,  # For vector status restoration
            "chunk_count": chunk_count,
        }

        if is_recovery:
            result["warning"] = (
                "Document was in permanent deletion process. "
                "Restoration successful, but verify data integrity."
            )

        return result

    def list_trash(
        self,
        namespace: Optional[str] = None,
        limit: int = 50,
        next_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """List trash entries using GSI1.

        All trash entries share GSI1PK="TRASH" for efficient querying.
        Namespace filtering is done via FilterExpression.

        Args:
            namespace: Optional namespace to filter trash
            limit: Maximum number of items to return (max 100)
            next_key: Pagination token from previous response

        Returns:
            Dictionary with documents list and optional next_key for pagination
        """
        limit = min(limit, 100)

        query_params = {
            "IndexName": "GSI1",
            "KeyConditionExpression": "GSI1PK = :pk",
            "ExpressionAttributeValues": {
                ":pk": "TRASH"
            },
            "Limit": limit,
            "ScanIndexForward": False,  # Most recent first
        }

        # Add namespace filter if specified
        if namespace:
            query_params["FilterExpression"] = "#ns = :namespace"
            query_params["ExpressionAttributeNames"] = {"#ns": "namespace"}
            query_params["ExpressionAttributeValues"][":namespace"] = namespace

        if next_key:
            query_params["ExclusiveStartKey"] = json.loads(
                base64.b64decode(next_key)
            )

        response = self.table.query(**query_params)
        items = response.get("Items", [])

        documents = [
            {
                "doc_id": item["doc_id"],
                "namespace": item["namespace"],
                "filename": item.get("filename"),
                "deleted_at": item.get("deleted_at"),
                "deleted_at_ms": int(item.get("deleted_at_ms", 0)),
                "deleted_by": item.get("deleted_by"),
                "delete_reason": item.get("delete_reason"),
                "chunk_count": item.get("chunk_count"),
                "purge_after": item.get("purge_after"),
                "days_until_purge": self._calculate_days_until_purge(item.get("purge_after")),
            }
            for item in items
            # Note: Trash entries are deleted immediately when permanent delete starts,
            # so only "deleting" status documents should appear here
        ]

        result = {"documents": documents}

        if "LastEvaluatedKey" in response:
            result["next_key"] = base64.b64encode(
                json.dumps(response["LastEvaluatedKey"]).encode()
            ).decode()

        return result

    def _calculate_days_until_purge(self, purge_after_iso: Optional[str]) -> Optional[int]:
        """Calculate days remaining until purge.

        Args:
            purge_after_iso: ISO 8601 timestamp string of purge deadline

        Returns:
            Number of days until purge, or None if not set
        """
        if not purge_after_iso:
            return None

        purge_after = datetime.fromisoformat(purge_after_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = purge_after - now
        return max(0, delta.days)

    def permanently_delete_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,
        deleted_by: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create cleanup job for permanent deletion.

        Args:
            doc_id: Document ID to permanently delete
            namespace: Document namespace
            deleted_at_ms: Deletion timestamp (for trash PK)
            deleted_by: Optional user ID who initiated permanent deletion
            filename: Filename from trash entry (uses doc metadata if not provided)

        Returns:
            Dictionary with cleanup job metadata
        """
        now = datetime.now(timezone.utc)
        cleanup_job_id = str(uuid.uuid4())

        # Get document metadata
        response = self.table.get_item(
            Key={
                "PK": f"DOC#{namespace}#{doc_id}",
                "SK": "METADATA"
            }
        )

        item = response.get("Item")
        if not item:
            raise ValueError(f"Document not found: {doc_id}")

        current_status = item.get("status")
        if current_status not in (DOC_STATUS_DELETING, DOC_STATUS_PURGING):
            raise ValueError(
                f"Document not in trash (status: {current_status}). "
                "Must soft delete first."
            )

        chunk_ids = item.get("chunk_ids", [])
        # Use provided filename (from trash entry) or fall back to doc metadata
        # This ensures we construct the correct trash PK even if filename changed
        trash_filename = filename if filename else item.get("filename", "unknown")

        # Check if already in purging state (retry scenario)
        already_purging = current_status == DOC_STATUS_PURGING
        existing_cleanup_job_id = item.get("cleanup_job_id")

        # If already purging and has cleanup job, don't create duplicate
        if already_purging and existing_cleanup_job_id:
            logger.info(
                "Document already being purged",
                extra={
                    "doc_id": doc_id,
                    "namespace": namespace,
                    "cleanup_job_id": existing_cleanup_job_id,
                }
            )
            return {
                "doc_id": doc_id,
                "namespace": namespace,
                "chunk_ids": chunk_ids,
                "chunk_count": len(chunk_ids),
                "cleanup_job_id": existing_cleanup_job_id,
                "status": "already_purging",
            }

        # Mark as purging, create cleanup job, and remove from trash view in transaction
        # Allow both deleting and purging status (for retries)
        self.client.transact_write_items(
            TransactItems=[
                {
                    # Mark doc as purging (or keep it purging if already)
                    "Update": {
                        "TableName": self.table.name,
                        "Key": {
                            "PK": {"S": f"DOC#{namespace}#{doc_id}"},
                            "SK": {"S": "METADATA"}
                        },
                        "UpdateExpression": "SET #status = :purging, purge_started_at = :now, cleanup_job_id = :job_id",
                        "ConditionExpression": "#status IN (:deleting, :purging)",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":purging": {"S": DOC_STATUS_PURGING},
                            ":deleting": {"S": DOC_STATUS_DELETING},
                            ":now": {"S": now.isoformat()},
                            ":job_id": {"S": cleanup_job_id},
                        }
                    }
                },
                {
                    # Create cleanup job
                    "Put": {
                        "TableName": self.table.name,
                        "Item": {
                            "PK": {"S": f"CLEANUP#{cleanup_job_id}"},
                            "SK": {"S": "JOB"},
                            "cleanup_job_id": {"S": cleanup_job_id},
                            "doc_id": {"S": doc_id},
                            "namespace": {"S": namespace},
                            "filename": {"S": trash_filename},  # Use trash filename for PK
                            "deleted_at_ms": {"N": str(deleted_at_ms)},
                            "chunk_ids": {"L": [{"S": cid} for cid in chunk_ids]},
                            "created_at": {"S": now.isoformat()},
                            "deleted_by": {"S": deleted_by} if deleted_by else {"NULL": True},
                            "status": {"S": "pending"},
                            "retry_count": {"N": "0"},
                            "max_retries": {"N": "10"},
                        }
                    }
                },
                {
                    # Delete trash entry immediately (removes from trash UI)
                    "Delete": {
                        "TableName": self.table.name,
                        "Key": {
                            "PK": {"S": f"TRASH#{namespace}#{trash_filename}#{deleted_at_ms}"},
                            "SK": {"S": "ENTRY"}
                        }
                    }
                }
            ]
        )

        logger.info(
            "Document marked for permanent deletion",
            extra={
                "doc_id": doc_id,
                "namespace": namespace,
                "cleanup_job_id": cleanup_job_id,
                "chunk_count": len(chunk_ids),
                "retry": already_purging,
            }
        )

        return {
            "doc_id": doc_id,
            "namespace": namespace,
            "chunk_ids": chunk_ids,
            "chunk_count": len(chunk_ids),
            "cleanup_job_id": cleanup_job_id,
        }

    def complete_permanent_delete(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,
        filename: str,
    ) -> None:
        """Complete permanent delete after vectors cleaned up.

        Args:
            doc_id: Document ID being purged
            namespace: Document namespace
            deleted_at_ms: Deletion timestamp (for trash PK)
            filename: Document filename (for trash PK)
        """
        now = datetime.now(timezone.utc)

        # Mark doc as purged and delete trash entry
        # Use condition to make this idempotent (only update if still purging)
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": {"S": f"DOC#{namespace}#{doc_id}"},
                                "SK": {"S": "METADATA"}
                            },
                            "UpdateExpression": (
                                "SET #status = :purged, purge_completed_at = :now "
                                "REMOVE chunk_ids, cleanup_job_id"
                            ),
                            "ConditionExpression": "#status = :purging",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": {
                                ":purged": {"S": DOC_STATUS_PURGED},
                                ":purging": {"S": DOC_STATUS_PURGING},
                                ":now": {"S": now.isoformat()},
                            }
                        }
                    },
                    {
                        "Delete": {
                            "TableName": self.table.name,
                            "Key": {
                                "PK": {"S": f"TRASH#{namespace}#{filename}#{deleted_at_ms}"},
                                "SK": {"S": "ENTRY"}
                            }
                        }
                    }
                ]
            )
            logger.info("Document permanently deleted", extra={"doc_id": doc_id, "namespace": namespace})
        except self.client.exceptions.TransactionCanceledException:
            # Already purged by another job (duplicate cleanup jobs)
            logger.info(
                "Document already purged (duplicate cleanup job)",
                extra={"doc_id": doc_id, "namespace": namespace}
            )

    def list_cleanup_jobs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List pending cleanup jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of cleanup job dictionaries
        """
        response = self.table.scan(
            FilterExpression="begins_with(PK, :prefix) AND #status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":prefix": "CLEANUP#",
                ":pending": "pending",
            },
            Limit=limit,
        )

        return [
            {
                "cleanup_job_id": item["cleanup_job_id"],
                "doc_id": item["doc_id"],
                "namespace": item["namespace"],
                "filename": item.get("filename", "unknown"),
                "deleted_at_ms": int(item.get("deleted_at_ms", 0)),
                "chunk_ids": item.get("chunk_ids", []),
                "created_at": item.get("created_at"),
                "retry_count": int(item.get("retry_count", 0)),
                "max_retries": int(item.get("max_retries", 10)),
            }
            for item in response.get("Items", [])
        ]

    def delete_cleanup_job(self, cleanup_job_id: str) -> None:
        """Delete completed cleanup job.

        Args:
            cleanup_job_id: Cleanup job ID
        """
        self.table.delete_item(
            Key={
                "PK": f"CLEANUP#{cleanup_job_id}",
                "SK": "JOB"
            }
        )
        logger.debug(f"Deleted cleanup job: {cleanup_job_id}")

    def mark_cleanup_job_failed(self, cleanup_job_id: str, error: str) -> None:
        """Increment retry count or move to DLQ.

        Args:
            cleanup_job_id: Cleanup job ID
            error: Error message to store
        """
        # Get current retry count
        response = self.table.get_item(
            Key={
                "PK": f"CLEANUP#{cleanup_job_id}",
                "SK": "JOB"
            }
        )

        item = response.get("Item")
        if not item:
            logger.warning(f"Cleanup job not found: {cleanup_job_id}")
            return

        retry_count = int(item.get("retry_count", 0))
        max_retries = int(item.get("max_retries", 10))

        if retry_count >= max_retries:
            # Move to DLQ
            logger.error(
                f"Cleanup job exceeded max retries, moving to DLQ",
                extra={"cleanup_job_id": cleanup_job_id, "error": error}
            )
            # In real implementation: write to SQS DLQ or DynamoDB DLQ table
        else:
            # Increment retry count
            self.table.update_item(
                Key={
                    "PK": f"CLEANUP#{cleanup_job_id}",
                    "SK": "JOB"
                },
                UpdateExpression="SET retry_count = retry_count + :inc, last_error = :error",
                ExpressionAttributeValues={
                    ":inc": 1,
                    ":error": error,
                }
            )

    def list_expired_trash(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List trash entries past purge_after date.

        Args:
            limit: Maximum number of items to return

        Returns:
            List of expired trash entries
        """
        now = datetime.now(timezone.utc).isoformat()

        response = self.table.scan(
            FilterExpression="begins_with(PK, :prefix) AND purge_after < :now",
            ExpressionAttributeValues={
                ":prefix": "TRASH#",
                ":now": now,
            },
            Limit=limit,
        )

        return [
            {
                "doc_id": item["doc_id"],
                "namespace": item["namespace"],
                "deleted_at_ms": int(item.get("deleted_at_ms", 0)),
                "purge_after": item.get("purge_after"),
            }
            for item in response.get("Items", [])
        ]
