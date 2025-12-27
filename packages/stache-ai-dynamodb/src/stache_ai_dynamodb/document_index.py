"""DynamoDB-backed document index provider"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError

from stache_ai.providers.base import DocumentIndexProvider

logger = logging.getLogger(__name__)


class DynamoDBDocumentIndex(DocumentIndexProvider):
    """DynamoDB-backed document index

    Implements DocumentIndexProvider using DynamoDB for efficient metadata-only
    queries without requiring vector database access.

    Schema:
    - PK: "DOC#{namespace}#{doc_id}"
    - SK: "METADATA"
    - GSI1PK: "NAMESPACE#{namespace}"
    - GSI1SK: "CREATED#{timestamp}"
    - GSI2PK: "FILENAME#{namespace}#{filename}"
    - GSI2SK: "CREATED#{timestamp}"
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

    def _make_gsi2pk(self, namespace: str, filename: str) -> str:
        """Create GSI2 partition key for filename lookups

        Args:
            namespace: Document namespace
            filename: Document filename

        Returns:
            GSI2 partition key in format: FILENAME#{namespace}#{filename}
        """
        return f"FILENAME#{namespace}#{filename}"

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
        file_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create document index entry

        Args:
            doc_id: Unique document identifier (typically UUID)
            filename: Original filename of the document
            namespace: Namespace/partition for the document
            chunk_ids: List of chunk IDs from vector database
            summary: Optional AI-generated summary of document
            summary_embedding_id: ID of the summary embedding in vector DB
            headings: Optional list of extracted headings from document
            metadata: Optional custom metadata dictionary
            file_type: Optional file type (pdf, epub, txt, md, etc.)
            file_size: Optional original file size in bytes

        Returns:
            Dictionary containing the created document record

        Raises:
            ClientError: If DynamoDB operation fails
        """
        created_at = datetime.now(timezone.utc).isoformat()

        item = {
            "PK": self._make_pk(namespace, doc_id),
            "SK": "METADATA",
            "GSI1PK": self._make_gsi1pk(namespace),
            "GSI1SK": self._make_gsi1sk(created_at),
            "GSI2PK": self._make_gsi2pk(namespace, filename),
            "GSI2SK": self._make_gsi1sk(created_at),
            "doc_id": doc_id,
            "filename": filename,
            "namespace": namespace,
            "chunk_count": len(chunk_ids),
            "created_at": created_at,
            "chunk_ids": chunk_ids,
        }

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
            self.table.put_item(Item=item)
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
                "IndexName": "GSI1-NamespaceCreated",
                "KeyConditionExpression": "GSI1PK = :pk",
                "ExpressionAttributeValues": {
                    ":pk": self._make_gsi1pk(namespace)
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
                IndexName="GSI2-FilenameCreated",
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

    def get_name(self) -> str:
        """Get the provider name

        Returns:
            Name of the document index provider
        """
        return "dynamodb-document-index"
