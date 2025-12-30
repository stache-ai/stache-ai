from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from fastapi import Request


@dataclass
class RequestContext:
    """Context passed to all middleware.

    The `custom` dict uses namespaced keys to avoid collisions:
    Example: custom["ACLMiddleware.allowed_ns"] = ["ns1", "ns2"]
    """
    request_id: str
    timestamp: datetime
    namespace: str

    # Identity
    user_id: str | None = None
    tenant_id: str | None = None
    roles: list[str] = field(default_factory=list)

    # Request metadata
    source: Literal["api", "mcp", "cli"] = "api"
    trace_id: str | None = None
    ip_address: str | None = None

    # Extensible (namespace keys: "MiddlewareName.key")
    custom: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_fastapi_request(cls, request: "Request", namespace: str) -> "RequestContext":
        """Create context from FastAPI request."""
        return cls(
            request_id=request.headers.get("x-request-id", str(uuid4())),
            timestamp=datetime.now(timezone.utc),
            namespace=namespace,
            user_id=getattr(request.state, "user_id", None),
            tenant_id=getattr(request.state, "tenant_id", None),
            roles=getattr(request.state, "roles", []),
            source="api",
            trace_id=request.headers.get("x-trace-id"),
            ip_address=request.client.host if request.client else None,
        )


@dataclass
class QueryContext:
    """Query-specific context using composition (not inheritance).

    Contains a RequestContext plus query-specific fields.
    """
    context: RequestContext
    query: str
    top_k: int
    filters: dict[str, Any] | None = None

    # Convenience properties
    @property
    def request_id(self) -> str:
        return self.context.request_id

    @property
    def namespace(self) -> str:
        return self.context.namespace

    @property
    def user_id(self) -> str | None:
        return self.context.user_id

    @property
    def tenant_id(self) -> str | None:
        return self.context.tenant_id

    @property
    def roles(self) -> list[str]:
        return self.context.roles

    @property
    def timestamp(self) -> datetime:
        return self.context.timestamp

    @property
    def source(self) -> Literal["api", "mcp", "cli"]:
        return self.context.source

    @property
    def trace_id(self) -> str | None:
        return self.context.trace_id

    @property
    def ip_address(self) -> str | None:
        return self.context.ip_address

    @property
    def custom(self) -> dict[str, Any]:
        return self.context.custom

    @classmethod
    def from_request_context(
        cls,
        context: RequestContext,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None
    ) -> "QueryContext":
        """Create QueryContext from existing RequestContext."""
        return cls(context=context, query=query, top_k=top_k, filters=filters)
