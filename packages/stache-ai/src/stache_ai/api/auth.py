"""Request principal extraction and authorization for API routes.

Reads the authorizer claims injected by API Gateway (surfaced by Mangum on
the ASGI scope as ``aws.event``) and returns a structured ``Principal``.
Claims are passed through opaquely — the core attaches no meaning to any
individual claim. ``assert_can_write`` re-exports the S1 authorization hook
and ``authorize`` is the per-route enforcement call, so routes have a single
import site.
"""

import logging

from stache_ai.identity import (  # noqa: F401
    ANONYMOUS,
    ApiGatewayClaimsExtractor,
    ForbiddenError,
    Principal,
    assert_can_write,
    get_authorizer,
)

logger = logging.getLogger(__name__)

_fallback_extractor = ApiGatewayClaimsExtractor()


def principal(request) -> Principal:
    """Return the authenticated caller as a Principal.

    The identity middleware extracts once per request and stashes the result
    on ``request.state.principal``; fall back to direct extraction for callers
    outside the ASGI app (tests, direct invocation).
    """
    existing = getattr(getattr(request, "state", None), "principal", None)
    if isinstance(existing, Principal):
        return existing
    return _fallback_extractor.extract(request)


def authorize(request, operation: str, resource: dict | None = None) -> None:
    """Enforce the pluggable authorization seam for a route (finding S1).

    Call BEFORE performing any work, outside broad try/except blocks so a
    denial surfaces as 403 rather than being swallowed into a 500.
    ``operation`` is a neutral verb string; ``resource`` is an opaque dict
    (include "namespace" when known, "owner" when cheaply available).
    Raises ForbiddenError on denial — the app maps it to a 403 response.
    """
    get_authorizer().authorize(principal(request), operation, resource)
