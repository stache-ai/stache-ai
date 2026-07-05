"""Request principal extraction + namespace write-authz hook.

Phase 1 records *who* submitted a job (Cognito JWT ``sub`` from the API Gateway
authorizer claims, surfaced by Mangum on the ASGI scope as ``aws.event``).
Namespace write enforcement is deferred to finding S1 - ``assert_can_write`` is
a clearly-marked no-op stub so S1 can fill it in without re-plumbing routes.
"""

import logging

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"


def principal(request) -> str:
    """Return the authenticated user id (Cognito JWT ``sub``), or 'anonymous'.

    Never trust a client-supplied identity - read only the authorizer claims
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
    sub = claims.get("sub")
    return sub or ANONYMOUS


def assert_can_write(principal: str, namespace: str) -> None:
    """Namespace write authorization hook.

    NO-OP in Phase 1. Enforcement is finding S1's responsibility; routes call
    this so the check lands in one place when S1 implements it.
    """
    return None
