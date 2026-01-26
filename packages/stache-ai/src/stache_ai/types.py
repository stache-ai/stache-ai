"""Type definitions for Stache API responses."""
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Any


class IngestionAction(str, Enum):
    """Actions taken during document ingestion."""
    INGEST_NEW = "ingested_new"
    SKIP = "skipped"
    REINGEST_VERSION = "ingested_version"
    METADATA_UPDATED = "metadata_updated"


@dataclass
class IngestionResult:
    """Result of document ingestion with deduplication info."""

    action: IngestionAction
    doc_id: str
    namespace: str
    chunks_created: int
    reason: str
    content_hash: str
    existing_hash: str | None = None
    previous_doc_id: str | None = None  # For REINGEST_VERSION
    version: int = 1
    timestamp: str | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        result = asdict(self)
        result["action"] = self.action.value
        return result

    # Backward compatibility: act like a dict
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
