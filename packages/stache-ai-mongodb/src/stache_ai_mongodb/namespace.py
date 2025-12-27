"""MongoDB namespace provider - Namespace registry using MongoDB"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from stache_ai.providers.base import NamespaceProvider
from stache_ai.config import Settings

logger = logging.getLogger(__name__)


class MongoDBNamespaceProvider(NamespaceProvider):
    """MongoDB-based namespace registry provider

    Uses a single collection with documents containing:
    - _id: namespace ID (string, used as primary key)
    - name: display name
    - description: namespace description
    - parent_id: parent namespace ID (null for root)
    - metadata: custom metadata dict
    - filter_keys: list of valid filter keys
    - created_at: ISO timestamp
    - updated_at: ISO timestamp

    Indexes created on init:
    - parent_id: for listing children
    - name: for sorting
    """

    def __init__(self, settings: Settings):
        """Initialize MongoDB namespace provider"""
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure

        self.client = MongoClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_database]
        self.collection = self.db[settings.mongodb_namespace_collection]

        try:
            self.client.admin.command('ping')
        except ConnectionFailure as e:
            raise ValueError(f"Cannot connect to MongoDB: {e}")

        self._ensure_indexes()
        logger.info(
            f"MongoDB namespace provider initialized: "
            f"{settings.mongodb_database}.{settings.mongodb_namespace_collection}"
        )

    def _ensure_indexes(self):
        """Create indexes for efficient querying"""
        from pymongo import ASCENDING

        # Index for listing children of a parent
        self.collection.create_index(
            [("parent_id", ASCENDING)],
            name="parent_id_idx"
        )

        # Index for sorting by name
        self.collection.create_index(
            [("name", ASCENDING)],
            name="name_idx"
        )

    def _to_mongo_doc(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert namespace data to MongoDB document (map id to _id)"""
        doc = data.copy()
        if "id" in doc:
            doc["_id"] = doc.pop("id")
        return doc

    def _from_mongo_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MongoDB document back to namespace dict (map _id to id)"""
        data = doc.copy()
        if "_id" in data:
            data["id"] = data.pop("_id")
        return data

    def create(
        self,
        id: str,
        name: str,
        description: str = "",
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        filter_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a new namespace"""
        from pymongo.errors import DuplicateKeyError

        now = datetime.now(timezone.utc).isoformat()

        # Validate parent exists if specified
        if parent_id and not self.exists(parent_id):
            raise ValueError(f"Parent namespace not found: {parent_id}")

        doc = {
            "_id": id,
            "name": name,
            "description": description,
            "parent_id": parent_id,
            "metadata": metadata or {},
            "filter_keys": filter_keys or [],
            "created_at": now,
            "updated_at": now
        }

        try:
            self.collection.insert_one(doc)
            logger.info(f"Created namespace: {id}")
        except DuplicateKeyError:
            raise ValueError(f"Namespace already exists: {id}")

        return self.get(id)

    def get(self, id: str) -> Optional[Dict[str, Any]]:
        """Get a namespace by ID"""
        doc = self.collection.find_one({"_id": id})
        return self._from_mongo_doc(doc) if doc else None

    def list(
        self,
        parent_id: Optional[str] = None,
        include_children: bool = False
    ) -> List[Dict[str, Any]]:
        """List namespaces, optionally filtered by parent"""
        if parent_id is None and not include_children:
            # Get root namespaces only
            cursor = self.collection.find({"parent_id": None}).sort("name", 1)
        elif parent_id is None and include_children:
            # Get all namespaces
            cursor = self.collection.find().sort("_id", 1)
        else:
            # Get children of specific parent
            cursor = self.collection.find({"parent_id": parent_id}).sort("name", 1)

        return [self._from_mongo_doc(doc) for doc in cursor]

    def update(
        self,
        id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        filter_keys: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Update a namespace"""
        existing = self.get(id)
        if not existing:
            return None

        # Build update fields
        update_doc = {}

        if name is not None:
            update_doc["name"] = name

        if description is not None:
            update_doc["description"] = description

        if parent_id is not None:
            # Validate parent exists
            if parent_id and not self.exists(parent_id):
                raise ValueError(f"Parent namespace not found: {parent_id}")
            # Prevent circular reference
            if parent_id == id:
                raise ValueError("Namespace cannot be its own parent")
            update_doc["parent_id"] = parent_id if parent_id else None

        if metadata is not None:
            # Merge with existing metadata
            merged = {**existing["metadata"], **metadata}
            update_doc["metadata"] = merged

        if filter_keys is not None:
            update_doc["filter_keys"] = filter_keys

        if not update_doc:
            return existing

        update_doc["updated_at"] = datetime.now(timezone.utc).isoformat()

        self.collection.update_one(
            {"_id": id},
            {"$set": update_doc}
        )
        logger.info(f"Updated namespace: {id}")

        return self.get(id)

    def delete(self, id: str, cascade: bool = False) -> bool:
        """Delete a namespace"""
        if not self.exists(id):
            return False

        # Check for children
        child_count = self.collection.count_documents({"parent_id": id})

        if child_count > 0 and not cascade:
            raise ValueError(
                f"Namespace has {child_count} children. Use cascade=True to delete."
            )

        if cascade:
            # Delete children recursively
            children = self.collection.find({"parent_id": id})
            for child_doc in children:
                self.delete(child_doc["_id"], cascade=True)

        self.collection.delete_one({"_id": id})
        logger.info(f"Deleted namespace: {id}")

        return True

    def get_tree(self, root_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get namespace hierarchy as a tree"""
        all_namespaces = self.list(include_children=True)

        # Build lookup dict
        by_id = {ns["id"]: {**ns, "children": []} for ns in all_namespaces}

        # Build tree structure
        roots = []
        for ns in all_namespaces:
            ns_with_children = by_id[ns["id"]]
            parent_id = ns["parent_id"]

            if parent_id and parent_id in by_id:
                by_id[parent_id]["children"].append(ns_with_children)
            elif parent_id is None:
                roots.append(ns_with_children)

        # If root_id specified, return just that subtree
        if root_id:
            if root_id in by_id:
                return [by_id[root_id]]
            return []

        return roots

    def exists(self, id: str) -> bool:
        """Check if a namespace exists"""
        return self.collection.count_documents({"_id": id}, limit=1) > 0

    def get_ancestors(self, id: str) -> List[Dict[str, Any]]:
        """Get all ancestor namespaces (parent, grandparent, etc.)"""
        ancestors = []
        current = self.get(id)

        while current and current["parent_id"]:
            parent = self.get(current["parent_id"])
            if parent:
                ancestors.append(parent)
                current = parent
            else:
                break

        return list(reversed(ancestors))  # Root first

    def get_path(self, id: str) -> str:
        """Get the full path of a namespace (e.g., 'MBA > Finance > Corporate Finance')"""
        ancestors = self.get_ancestors(id)
        current = self.get(id)

        if not current:
            return ""

        names = [a["name"] for a in ancestors] + [current["name"]]
        return " > ".join(names)

    def close(self):
        """Close the MongoDB connection"""
        if hasattr(self, 'client') and self.client:
            self.client.close()
            logger.info("MongoDB namespace provider connection closed")
