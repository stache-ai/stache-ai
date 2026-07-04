"""Caller identity for API routes, ingestion seams, and providers.

``Principal`` is the structured "who is calling" value. OSS knows only the
user id and an opaque claims dict; it attaches no meaning to any claim.
Deployment-specific extensions (organizations, roles, plans) live entirely in
external packages that read ``claims`` — the core never interprets them.

``assert_can_write`` is the namespace write-authorization hook (finding S1).
It is a no-op here; enforcement ships as a pluggable authorizer.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"


class AuthenticationError(Exception):
    """Raised by a PrincipalExtractor when the caller cannot be authenticated.

    The API layer maps this to a 401. The core NEVER swallows it into an
    anonymous principal — a configured extractor is fail-closed.
    """


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


class PrincipalExtractor(ABC):
    """Pluggable "who is calling" extraction (entry point: stache.principal_extractor).

    The default reads API Gateway authorizer claims and falls back to the
    anonymous principal — the OSS single-user posture. Deployment-specific
    extractors (which verify JWTs themselves and refuse unauthenticated
    callers) replace it via config; when one is configured it is fail-closed:
    load failures abort startup and extraction failures become 401s.
    """

    @abstractmethod
    def extract(self, request) -> Principal:
        """Return the caller's Principal or raise AuthenticationError."""


class ApiGatewayClaimsExtractor(PrincipalExtractor):
    """Default extractor: API Gateway authorizer claims via Mangum's aws.event.

    Never trusts a client-supplied identity — reads only the authorizer claims
    injected by API Gateway. Supports HTTP API v2 (``authorizer.jwt.claims``)
    and REST API (``authorizer.claims``) event shapes. Unauthenticated calls
    yield the anonymous principal (gateway config decides whether those exist).
    """

    def __init__(self, config=None):
        self._config = config

    def extract(self, request) -> Principal:
        try:
            event = request.scope.get("aws.event") or {}
        except AttributeError:
            event = {}
        request_context = event.get("requestContext", {}) or {}
        authorizer = request_context.get("authorizer", {}) or {}
        jwt = authorizer.get("jwt", {}) or {}
        claims = jwt.get("claims") or authorizer.get("claims") or {}
        return Principal(user_id=claims.get("sub") or ANONYMOUS, claims=dict(claims))


DEFAULT_EXTRACTOR = "apigateway"


def build_extractor(config) -> PrincipalExtractor:
    """Instantiate the configured principal extractor. FAIL-CLOSED.

    A misconfigured or unloadable non-default extractor raises instead of
    silently falling back to the permissive default — falling back would turn
    an auth deployment into an unauthenticated one.
    """
    name = getattr(config, "principal_extractor", DEFAULT_EXTRACTOR)
    if name == DEFAULT_EXTRACTOR:
        return ApiGatewayClaimsExtractor(config)
    from stache_ai.providers.plugin_loader import get_providers
    available = get_providers("principal_extractor")
    if name not in available:
        raise RuntimeError(
            f"Configured principal extractor '{name}' is not installed "
            f"(available: {sorted(available) or 'none'}). Refusing to fall "
            f"back to the default extractor."
        )
    cls = available[name]
    try:
        return cls(config)
    except TypeError:
        return cls()
