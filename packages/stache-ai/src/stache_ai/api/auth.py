"""Request principal extraction for API routes.

Reads the authorizer claims injected by API Gateway (surfaced by Mangum on
the ASGI scope as ``aws.event``) and returns a structured ``Principal``.
Claims are passed through opaquely — the core attaches no meaning to any
individual claim. ``assert_can_write`` re-exports the S1 authorization hook
so routes have a single import site.
"""

import logging

from stache_ai.identity import (  # noqa: F401
    ANONYMOUS,
    ApiGatewayClaimsExtractor,
    Principal,
    assert_can_write,
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
