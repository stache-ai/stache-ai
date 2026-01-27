"""MongoDB-backed document index provider"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from stache_ai.providers.base import DocumentIndexProvider
from stache_ai.config import Settings

logger = logging.getLogger(__name__)


class MongoDBDocumentIndex(DocumentIndexProvider):
    """MongoDB-backed document index

    Schema uses compound _id: {"namespace": str, "doc_id": str}

    Indexes created:
    - {namespace: 1, created_at: -1} - For namespace listing (most recent first)
    - {namespace: 1, filename: 1} - For filename existence checks
    """

    def __init__(self, settings: Settings):
        """Initialize MongoDB document index

        Args:
            settings: Settings object with MongoDB configuration

        Raises:
            ValueError: If cannot connect to MongoDB
        """
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure

        self.client = MongoClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_database]
        self.collection = self.db[settings.mongodb_documents_collection]

        # Validate connection
        try:
            self.client.admin.command('ping')
        except ConnectionFailure as e:
            raise ValueError(f"Cannot connect to MongoDB: {e}")

        self._ensure_indexes()
        logger.info(
            f"MongoDB document index initialized: "
            f"{settings.mongodb_database}.{settings.mongodb_documents_collection}"
        )

    def _ensure_indexes(self):
        """Create required indexes for efficient querying"""
        from pymongo import ASCENDING, DESCENDING

        # Index for namespace listing sorted by creation date (most recent first)
        self.collection.create_index(
            [("namespace", ASCENDING), ("created_at", DESCENDING)],
            name="namespace_created"
        )

        # Index for filename existence checks
        self.collection.create_index(
            [("namespace", ASCENDING), ("filename", ASCENDING)],
            name="namespace_filename"
        )

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
            Exception: If MongoDB operation fails
        """
        created_at = datetime.now(timezone.utc).isoformat()

        document = {
            "_id": {"namespace": namespace, "doc_id": doc_id},
            "doc_id": doc_id,
            "filename": filename,
            "namespace": namespace,
            "chunk_count": len(chunk_ids),
            "created_at": created_at,
            "chunk_ids": chunk_ids,
        }

        # Optional fields - only include if provided
        if summary:
            document["summary"] = summary
        if summary_embedding_id:
            document["summary_embedding_id"] = summary_embedding_id
        if headings:
            document["headings"] = headings
        if metadata:
            document["metadata"] = metadata
        if file_type:
            document["file_type"] = file_type
        if file_size is not None:
            document["file_size"] = file_size

        try:
            self.collection.insert_one(document)
            logger.info(f"Created document index: {doc_id} in namespace {namespace}")
            return document
        except Exception as e:
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
            Exception: If MongoDB operation fails
        """
        if not namespace:
            raise ValueError("Namespace is required for get_document in MongoDB provider")

        try:
            document = self.collection.find_one({
                "_id": {"namespace": namespace, "doc_id": doc_id}
            })
            return document
        except Exception as e:
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
            Exception: If MongoDB operation fails
        """
        query = {}
        if namespace:
            query["namespace"] = namespace

        # If pagination token provided, filter by creation date
        if last_evaluated_key:
            query["created_at"] = {"$lt": last_evaluated_key.get("created_at")}

        try:
            # Query with limit + 1 to detect if there are more results
            cursor = (
                self.collection.find(query)
                .sort("created_at", -1)  # Most recent first
                .limit(limit + 1)
            )
            documents = list(cursor)

            next_key = None
            if len(documents) > limit:
                # More results exist
                documents = documents[:limit]
                next_key = {"created_at": documents[-1]["created_at"]}

            return {
                "documents": documents,
                "next_key": next_key
            }
        except Exception as e:
            error_msg = "Failed to list documents"
            if namespace:
                error_msg += f" in namespace {namespace}"
            error_msg += f": {e}"
            logger.error(error_msg)
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
            Exception: If MongoDB operation fails
        """
        if not namespace:
            raise ValueError("Namespace is required for delete_document in MongoDB provider")

        try:
            result = self.collection.delete_one({
                "_id": {"namespace": namespace, "doc_id": doc_id}
            })
            if result.deleted_count > 0:
                logger.info(f"Deleted document index: {doc_id} from namespace {namespace}")
                return True
            return False
        except Exception as e:
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
            Exception: If MongoDB operation fails
        """
        if not namespace:
            raise ValueError(
                "Namespace is required for update_document_summary in MongoDB provider"
            )

        try:
            result = self.collection.update_one(
                {"_id": {"namespace": namespace, "doc_id": doc_id}},
                {
                    "$set": {
                        "summary": summary,
                        "summary_embedding_id": summary_embedding_id
                    }
                }
            )
            if result.matched_count > 0:
                logger.info(f"Updated summary for document {doc_id} in namespace {namespace}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to update summary for {doc_id}: {e}")
            raise

    def update_document_metadata(
        self,
        doc_id: str,
        namespace: str,
        updates: dict[str, Any]
    ) -> bool:
        """Update document metadata (namespace, filename, custom metadata)

        For namespace migration, uses transactions if replica set available,
        otherwise falls back to delete+insert.

        Args:
            doc_id: Document identifier to update
            namespace: Current namespace for the document (required)
            updates: Dictionary containing fields to update:
                - namespace: New namespace to migrate document to (optional)
                - filename: New filename (optional)
                - metadata: New metadata dictionary to replace existing (optional)

        Returns:
            True if update was successful, False if document not found

        Raises:
            ValueError: If namespace is not provided
            Exception: If MongoDB operation fails
        """
        from pymongo.errors import ConfigurationError, OperationFailure

        if not namespace:
            raise ValueError(
                "Namespace is required for update_document_metadata in MongoDB provider"
            )

        # Extract fields from updates dict
        new_namespace = updates.get("namespace")
        new_filename = updates.get("filename")
        metadata = updates.get("metadata")

        # Namespace migration requires special handling (delete+insert or transaction)
        if new_namespace and new_namespace != namespace:
            # Try transaction first (replica set), fall back to delete+insert
            try:
                with self.client.start_session() as session:
                    with session.start_transaction():
                        # Fetch existing document
                        old_id = {"namespace": namespace, "doc_id": doc_id}
                        doc = self.collection.find_one({"_id": old_id}, session=session)
                        if not doc:
                            return False

                        # Update namespace in document
                        doc["_id"] = {"namespace": new_namespace, "doc_id": doc_id}
                        doc["namespace"] = new_namespace

                        # Update other fields if provided
                        if new_filename:
                            doc["filename"] = new_filename
                        if metadata is not None:
                            doc["metadata"] = metadata

                        # Delete from old namespace, insert to new
                        self.collection.delete_one({"_id": old_id}, session=session)
                        self.collection.insert_one(doc, session=session)

                        # Transaction commits automatically when context exits
                        logger.info(
                            f"Migrated document {doc_id} from {namespace} to {new_namespace}"
                        )
                        return True

            except (ConfigurationError, OperationFailure) as e:
                # Replica set not available, fall back to delete+insert
                logger.warning(
                    f"Transactions not supported, using delete+insert for migration: {e}"
                )
                old_id = {"namespace": namespace, "doc_id": doc_id}
                doc = self.collection.find_one({"_id": old_id})
                if not doc:
                    return False

                # Update document
                doc["_id"] = {"namespace": new_namespace, "doc_id": doc_id}
                doc["namespace"] = new_namespace
                if new_filename:
                    doc["filename"] = new_filename
                if metadata is not None:
                    doc["metadata"] = metadata

                # Delete+insert (not atomic but best we can do)
                self.collection.delete_one({"_id": old_id})
                self.collection.insert_one(doc)
                logger.info(
                    f"Migrated document {doc_id} from {namespace} to {new_namespace} "
                    "(no transaction)"
                )
                return True

        # In-place updates (no namespace change)
        else:
            update_fields = {}
            if new_filename:
                update_fields["filename"] = new_filename
            if metadata is not None:
                update_fields["metadata"] = metadata

            if not update_fields:
                # No updates to perform
                return True

            try:
                result = self.collection.update_one(
                    {"_id": {"namespace": namespace, "doc_id": doc_id}},
                    {"$set": update_fields}
                )
                if result.matched_count > 0:
                    logger.info(f"Updated metadata for document {doc_id} in namespace {namespace}")
                    return True
                return False
            except Exception as e:
                logger.error(f"Failed to update metadata for {doc_id}: {e}")
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
        except (ValueError, Exception):
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
            document = self.collection.find_one({
                "filename": filename,
                "namespace": namespace
            })
            return document is not None
        except Exception as e:
            logger.error(f"Failed to check document existence for {filename}: {e}")
            return False

    def get_name(self) -> str:
        """Get the provider name

        Returns:
            Name of the document index provider
        """
        return "mongodb-document-index"

    # ==================== Deduplication Methods (Not Implemented) ====================

    def reserve_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        doc_id: str,
        source_path: str | None = None,
        file_size: int | None = None,
        file_modified_at: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> bool:
        """MongoDB provider does not support deduplication features"""
        raise NotImplementedError(
            "MongoDB provider does not support hash-based deduplication. "
            "Use DynamoDB provider for deduplication features."
        )

    def get_document_by_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: str | None = None
    ) -> dict[str, Any] | None:
        """MongoDB provider does not support deduplication features"""
        raise NotImplementedError(
            "MongoDB provider does not support hash-based deduplication. "
            "Use DynamoDB provider for deduplication features."
        )

    def complete_identifier_reservation(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        doc_id: str,
        chunk_count: int,
        source_path: str | None = None
    ) -> None:
        """MongoDB provider does not support deduplication features"""
        raise NotImplementedError(
            "MongoDB provider does not support hash-based deduplication. "
            "Use DynamoDB provider for deduplication features."
        )

    def release_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: str | None = None
    ) -> None:
        """MongoDB provider does not support deduplication features"""
        raise NotImplementedError(
            "MongoDB provider does not support hash-based deduplication. "
            "Use DynamoDB provider for deduplication features."
        )

    # ==================== Soft Delete / Trash Methods (Not Implemented) ====================

    def soft_delete_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_by: str | None = None,
        delete_reason: str = "user_initiated"
    ) -> dict[str, Any]:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def restore_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,
        restored_by: str | None = None
    ) -> dict[str, Any]:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def list_trash(
        self,
        namespace: str | None = None,
        limit: int = 50,
        next_key: str | None = None
    ) -> dict[str, Any]:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def permanently_delete_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,
        deleted_by: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def complete_permanent_delete(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,
        filename: str,
    ) -> None:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def list_cleanup_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def delete_cleanup_job(self, cleanup_job_id: str) -> None:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def mark_cleanup_job_failed(
        self,
        cleanup_job_id: str,
        error_message: str
    ) -> None:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def list_expired_trash(
        self,
        limit: int = 100,
        next_key: str | None = None
    ) -> dict[str, Any]:
        """MongoDB provider does not support trash/restore features"""
        raise NotImplementedError(
            "MongoDB provider does not support soft delete and trash features. "
            "Use DynamoDB provider for trash/restore functionality."
        )

    def close(self):
        """Close the MongoDB connection"""
        if hasattr(self, 'client') and self.client:
            self.client.close()
            logger.info("MongoDB document index connection closed")
