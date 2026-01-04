"""Redis namespace provider - Network-accessible namespace registry using Redis"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import redis

from stache_ai.providers.base import NamespaceProvider
from stache_ai.config import Settings

logger = logging.getLogger(__name__)

# Redis key prefixes
NS_KEY_PREFIX = "stache:namespace:"
NS_INDEX_KEY = "stache:namespaces"  # Set of all namespace IDs


class RedisNamespaceProvider(NamespaceProvider):
    """Redis-based namespace registry provider.

    Stores namespaces as JSON in Redis with:
    - Individual keys for each namespace: stache:namespace:{id}
    - A set index of all namespace IDs: stache:namespaces

    Supports Redis persistence (RDB/AOF) for durability.
    """

    def __init__(self, settings: Settings):
        self.client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True  # Return strings instead of bytes
        )
        # Test connection
        try:
            self.client.ping()
            logger.info(f"Redis namespace provider connected: {settings.redis_host}:{settings.redis_port}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _ns_key(self, id: str) -> str:
        """Get Redis key for a namespace"""
        return f"{NS_KEY_PREFIX}{id}"

    def _serialize(self, ns: Dict[str, Any]) -> str:
        """Serialize namespace to JSON"""
        return json.dumps(ns)

    def _deserialize(self, data: str) -> Dict[str, Any]:
        """Deserialize namespace from JSON"""
        ns = json.loads(data)
        # Ensure metadata is a dict
        if isinstance(ns.get("metadata"), str):
            ns["metadata"] = json.loads(ns["metadata"])
        # Ensure filter_keys exists (backward compatibility)
        if "filter_keys" not in ns:
            ns["filter_keys"] = []
        return ns

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
        # Check if already exists
        if self.exists(id):
            raise ValueError(f"Namespace already exists: {id}")

        # Validate parent exists if specified
        if parent_id and not self.exists(parent_id):
            raise ValueError(f"Parent namespace not found: {parent_id}")

        now = datetime.now(timezone.utc).isoformat()
        ns = {
            "id": id,
            "name": name,
            "description": description,
            "parent_id": parent_id,
            "metadata": metadata or {},
            "filter_keys": filter_keys or [],
            "created_at": now,
            "updated_at": now
        }

        # Use pipeline for atomic operation
        pipe = self.client.pipeline()
        pipe.set(self._ns_key(id), self._serialize(ns))
        pipe.sadd(NS_INDEX_KEY, id)
        pipe.execute()

        logger.info(f"Created namespace: {id}")
        return ns

    def get(self, id: str) -> Optional[Dict[str, Any]]:
        """Get a namespace by ID"""
        data = self.client.get(self._ns_key(id))
        if data is None:
            return None
        return self._deserialize(data)

    def list(
        self,
        parent_id: Optional[str] = None,
        include_children: bool = False
    ) -> List[Dict[str, Any]]:
        """List namespaces, optionally filtered by parent"""
        # Get all namespace IDs
        all_ids = self.client.smembers(NS_INDEX_KEY)
        if not all_ids:
            return []

        # Fetch all namespaces
        pipe = self.client.pipeline()
        for ns_id in all_ids:
            pipe.get(self._ns_key(ns_id))
        results = pipe.execute()

        namespaces = []
        for data in results:
            if data:
                namespaces.append(self._deserialize(data))

        # Filter based on parameters
        if parent_id is None and not include_children:
            # Get root namespaces only
            namespaces = [ns for ns in namespaces if ns["parent_id"] is None]
        elif parent_id is not None:
            # Get children of specific parent
            namespaces = [ns for ns in namespaces if ns["parent_id"] == parent_id]
        # else: include_children=True, return all

        # Sort by name or id
        if parent_id is None and include_children:
            namespaces.sort(key=lambda x: x["id"])
        else:
            namespaces.sort(key=lambda x: x["name"])

        return namespaces

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

        # Apply updates
        if name is not None:
            existing["name"] = name

        if description is not None:
            existing["description"] = description

        if parent_id is not None:
            # Validate parent exists
            if parent_id and not self.exists(parent_id):
                raise ValueError(f"Parent namespace not found: {parent_id}")
            # Prevent circular reference
            if parent_id == id:
                raise ValueError("Namespace cannot be its own parent")
            existing["parent_id"] = parent_id if parent_id else None

        if metadata is not None:
            # Merge with existing metadata
            existing["metadata"] = {**existing.get("metadata", {}), **metadata}

        # NEW: Handle filter_keys (replace, not merge)
        if filter_keys is not None:
            existing["filter_keys"] = filter_keys

        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Save
        self.client.set(self._ns_key(id), self._serialize(existing))
        logger.info(f"Updated namespace: {id}")

        return existing

    def delete(self, id: str, cascade: bool = False) -> bool:
        """Delete a namespace"""
        if not self.exists(id):
            return False

        # Check for children
        children = self.list(parent_id=id)
        if children and not cascade:
            raise ValueError(
                f"Namespace has {len(children)} children. Use cascade=True to delete."
            )

        # Delete children recursively if cascade
        if cascade:
            for child in children:
                self.delete(child["id"], cascade=True)

        # Delete the namespace
        pipe = self.client.pipeline()
        pipe.delete(self._ns_key(id))
        pipe.srem(NS_INDEX_KEY, id)
        pipe.execute()

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
        return self.client.exists(self._ns_key(id)) > 0

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
