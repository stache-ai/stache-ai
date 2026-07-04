"""Caller identity for API routes, ingestion seams, and providers.

``Principal`` is the structured "who is calling" value. OSS knows only the
user id and an opaque claims dict; it attaches no meaning to any claim.
Deployment-specific extensions (organizations, roles, plans) live entirely in
external packages that read ``claims`` — the core never interprets them.

``AuthorizationProvider`` is the pluggable authorization seam (finding S1).
The default ``AllowAllAuthorizer`` preserves the OSS single-user posture;
deployment-specific policy plugs in via the ``stache.authorizer`` entry point
and is fail-closed: a configured-but-unloadable authorizer aborts startup.
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


class ForbiddenError(Exception):
    """Raised by an AuthorizationProvider to deny an operation.

    The API layer maps this to a 403. The ingestion worker lets it fail the
    job. The core never catches-and-continues past a denial.
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


class AuthorizationProvider(ABC):
    """Pluggable authorization seam (entry point: stache.authorizer).

    Contract: ``authorize`` returns None to allow, raises ForbiddenError to
    deny. ``operation`` is a neutral verb string (e.g. "ingest",
    "delete_document"); ``resource`` is an opaque dict with keys like
    "namespace" or "owner" when available. The core attaches no policy of its
    own — actual rules live entirely in external packages.
    """

    @abstractmethod
    def authorize(self, principal: Principal, operation: str, resource: dict | None = None) -> None:
        """Allow (return None) or deny (raise ForbiddenError) an operation."""


class AllowAllAuthorizer(AuthorizationProvider):
    """Default authorizer: every operation is allowed (OSS single-user posture)."""

    def __init__(self, config=None):
        self._config = config

    def authorize(self, principal: Principal, operation: str, resource: dict | None = None) -> None:
        return None


DEFAULT_AUTHORIZER = "allow-all"


def build_authorizer(config) -> AuthorizationProvider:
    """Instantiate the configured authorizer. FAIL-CLOSED.

    Unset/None/"allow-all" yields the permissive default. Any other value must
    resolve via the ``stache.authorizer`` entry point group; a misconfigured or
    unloadable authorizer raises instead of silently falling back — falling
    back would strip enforcement from a deployment that configured it.
    """
    name = getattr(config, "authorization_provider", None)
    if name in (None, "", DEFAULT_AUTHORIZER):
        return AllowAllAuthorizer(config)
    from stache_ai.providers.plugin_loader import get_providers
    available = get_providers("authorizer")
    if name not in available:
        raise RuntimeError(
            f"Configured authorization provider '{name}' is not installed "
            f"(available: {sorted(available) or 'none'}). Refusing to fall "
            f"back to the allow-all authorizer."
        )
    cls = available[name]
    try:
        return cls(config)
    except TypeError:
        return cls()


_authorizer: AuthorizationProvider | None = None


def get_authorizer() -> AuthorizationProvider:
    """Process-wide authorizer built lazily from the global settings."""
    global _authorizer
    if _authorizer is None:
        from stache_ai.config import settings
        _authorizer = build_authorizer(settings)
        logger.info(f"Authorization provider: {type(_authorizer).__name__}")
    return _authorizer


def reset_authorizer() -> None:
    """Discard the cached authorizer (tests / config reloads)."""
    global _authorizer
    _authorizer = None


def assert_can_write(principal: Principal, namespace: str) -> None:
    """Namespace write authorization hook (finding S1).

    Delegates to the configured authorizer so route intake, the ingestion
    worker, and the producer-drop path all enforce through one seam. Raises
    ForbiddenError on denial.
    """
    get_authorizer().authorize(principal, "ingest", {"namespace": namespace})


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
