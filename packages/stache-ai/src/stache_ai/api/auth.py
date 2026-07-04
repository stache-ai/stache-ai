"""Request principal extraction for API routes.

Reads the authorizer claims injected by API Gateway (surfaced by Mangum on
the ASGI scope as ``aws.event``) and returns a structured ``Principal``.
Claims are passed through opaquely — the core attaches no meaning to any
individual claim. ``assert_can_write`` re-exports the S1 authorization hook
so routes have a single import site.
"""

import logging

from stache_ai.identity import ANONYMOUS, Principal, assert_can_write  # noqa: F401

logger = logging.getLogger(__name__)


def principal(request) -> Principal:
    """Return the authenticated caller as a Principal.

    Never trust a client-supplied identity — read only the authorizer claims
    injected by API Gateway. Supports both HTTP API v2 (``authorizer.jwt.claims``)
    and REST API (``authorizer.claims``) event shapes.
    """
    try:
        event = request.scope.get("aws.event") or {}
    except AttributeError:
        event = {}
    request_context = event.get("requestContext", {}) or {}
    authorizer = request_context.get("authorizer", {}) or {}
    # HTTP API v2 nests JWT claims under "jwt"; REST API puts them at "claims".
    jwt = authorizer.get("jwt", {}) or {}
    claims = jwt.get("claims") or authorizer.get("claims") or {}
    return Principal(user_id=claims.get("sub") or ANONYMOUS, claims=dict(claims))
