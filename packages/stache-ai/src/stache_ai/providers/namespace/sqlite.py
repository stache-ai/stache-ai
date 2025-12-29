"""SQLite namespace provider - Lightweight namespace registry using SQLite"""

import builtins
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stache_ai.config import Settings
from stache_ai.providers.base import NamespaceProvider

logger = logging.getLogger(__name__)


class SQLiteNamespaceProvider(NamespaceProvider):
    """SQLite-based namespace registry provider"""

    def __init__(self, settings: Settings):
        self.db_path = Path(settings.namespace_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"SQLite namespace provider initialized: {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS namespaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    parent_id TEXT,
                    metadata TEXT DEFAULT '{}',
                    filter_keys TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES namespaces(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_namespaces_parent
                ON namespaces(parent_id)
            """)

            # Migration: Add filter_keys column if it doesn't exist (for existing databases)
            cursor = conn.execute("PRAGMA table_info(namespaces)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'filter_keys' not in columns:
                conn.execute("ALTER TABLE namespaces ADD COLUMN filter_keys TEXT DEFAULT '[]'")
                conn.commit()
                logger.info("Migrated namespaces table: added filter_keys column")

            conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to a dictionary"""
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "parent_id": row["parent_id"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "filter_keys": json.loads(row["filter_keys"]) if row["filter_keys"] else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

    def create(
        self,
        id: str,
        name: str,
        description: str = "",
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        filter_keys: list[str] | None = None
    ) -> dict[str, Any]:
        """Create a new namespace"""
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {})
        filter_keys_json = json.dumps(filter_keys or [])

        # Validate parent exists if specified
        if parent_id and not self.exists(parent_id):
            raise ValueError(f"Parent namespace not found: {parent_id}")

        with self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO namespaces (id, name, description, parent_id, metadata, filter_keys, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (id, name, description, parent_id, metadata_json, filter_keys_json, now, now)
                )
                conn.commit()
                logger.info(f"Created namespace: {id}")
            except sqlite3.IntegrityError:
                raise ValueError(f"Namespace already exists: {id}")

        return self.get(id)

    def get(self, id: str) -> dict[str, Any] | None:
        """Get a namespace by ID"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM namespaces WHERE id = ?",
                (id,)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None

    def list(
        self,
        parent_id: str | None = None,
        include_children: bool = False
    ) -> list[dict[str, Any]]:
        """List namespaces, optionally filtered by parent"""
        with self._get_connection() as conn:
            if parent_id is None and not include_children:
                # Get root namespaces only
                cursor = conn.execute(
                    "SELECT * FROM namespaces WHERE parent_id IS NULL ORDER BY name"
                )
            elif parent_id is None and include_children:
                # Get all namespaces
                cursor = conn.execute(
                    "SELECT * FROM namespaces ORDER BY id"
                )
            else:
                # Get children of specific parent
                cursor = conn.execute(
                    "SELECT * FROM namespaces WHERE parent_id = ? ORDER BY name",
                    (parent_id,)
                )

            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def update(
        self,
        id: str,
        name: str | None = None,
        description: str | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        filter_keys: builtins.list[str] | None = None
    ) -> dict[str, Any] | None:
        """Update a namespace"""
        existing = self.get(id)
        if not existing:
            return None

        # Build update fields
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if parent_id is not None:
            # Validate parent exists
            if parent_id and not self.exists(parent_id):
                raise ValueError(f"Parent namespace not found: {parent_id}")
            # Prevent circular reference
            if parent_id == id:
                raise ValueError("Namespace cannot be its own parent")
            updates.append("parent_id = ?")
            params.append(parent_id if parent_id else None)

        if metadata is not None:
            # Merge with existing metadata
            merged = {**existing["metadata"], **metadata}
            updates.append("metadata = ?")
            params.append(json.dumps(merged))

        if filter_keys is not None:
            updates.append("filter_keys = ?")
            params.append(json.dumps(filter_keys))

        if not updates:
            return existing

        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(id)

        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE namespaces SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
            logger.info(f"Updated namespace: {id}")

        return self.get(id)

    def delete(self, id: str, cascade: bool = False) -> bool:
        """Delete a namespace"""
        if not self.exists(id):
            return False

        with self._get_connection() as conn:
            # Check for children
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM namespaces WHERE parent_id = ?",
                (id,)
            )
            child_count = cursor.fetchone()["count"]

            if child_count > 0 and not cascade:
                raise ValueError(
                    f"Namespace has {child_count} children. Use cascade=True to delete."
                )

            if cascade:
                # Delete children recursively
                cursor = conn.execute(
                    "SELECT id FROM namespaces WHERE parent_id = ?",
                    (id,)
                )
                for row in cursor.fetchall():
                    self.delete(row["id"], cascade=True)

            conn.execute("DELETE FROM namespaces WHERE id = ?", (id,))
            conn.commit()
            logger.info(f"Deleted namespace: {id}")

        return True

    def get_tree(self, root_id: str | None = None) -> builtins.list[dict[str, Any]]:
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
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM namespaces WHERE id = ?",
                (id,)
            )
            return cursor.fetchone() is not None

    def get_ancestors(self, id: str) -> builtins.list[dict[str, Any]]:
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
