"""Caller identity for API routes, ingestion seams, and providers.

``Principal`` is the structured "who is calling" value. OSS knows only the
user id and an opaque claims dict; it attaches no meaning to any claim.
Deployment-specific extensions (organizations, roles, plans) live entirely in
external packages that read ``claims`` — the core never interprets them.

``assert_can_write`` is the namespace write-authorization hook (finding S1).
It is a no-op here; enforcement ships as a pluggable authorizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller.

    ``user_id`` is the verified subject (JWT ``sub``), or ``anonymous`` when
    unauthenticated — the OSS single-user posture. ``claims`` is the verified
    claim set, passed through opaquely for external packages to interpret.
    """

    user_id: str = ANONYMOUS
    claims: dict = field(default_factory=dict)

    @property
    def is_anonymous(self) -> bool:
        return self.user_id == ANONYMOUS

    @classmethod
    def of(cls, value: "Principal | str | None") -> "Principal":
        """Normalize a user-id string (legacy callers) or None to a Principal."""
        if isinstance(value, Principal):
            return value
        return cls(user_id=value or ANONYMOUS)


def assert_can_write(principal: Principal, namespace: str) -> None:
    """Namespace write authorization hook.

    NO-OP stub (finding S1). Routes and the ingestion worker call this so
    enforcement lands in one place when an authorizer is installed.
    """
    return None
