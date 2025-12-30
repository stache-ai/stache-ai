from __future__ import annotations

import asyncio
import time
import logging
from collections import defaultdict
from typing import TypeVar, Generic, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import MiddlewareBase
    from .context import RequestContext
    from .results import EnrichmentResult, QueryProcessorResult

logger = logging.getLogger(__name__)

T = TypeVar('T')
R = TypeVar('R')


class MiddlewareError(Exception):
    """Raised when middleware fails and on_error=reject."""
    def __init__(self, middleware_name: str, reason: str):
        self.middleware_name = middleware_name
        self.reason = reason
        super().__init__(f"Middleware {middleware_name} failed: {reason}")


class MiddlewareRejection(Exception):
    """Raised when middleware explicitly rejects an operation."""
    def __init__(self, middleware_name: str, reason: str | None):
        self.middleware_name = middleware_name
        self.reason = reason
        super().__init__(f"Rejected by {middleware_name}: {reason}")


class MiddlewareChain(Generic[T, R]):
    """Executes middleware in dependency order with error handling.

    Type parameters:
        T: The value type being processed (e.g., str for content, list for results)
        R: The result type returned by middleware (e.g., EnrichmentResult)

    Design Note:
        The pipeline currently uses direct iteration over middleware lists for flexibility
        in handling different middleware types (enrichers, observers, processors) which may
        have varying method signatures. MiddlewareChain is available for custom use cases
        that benefit from centralized dependency ordering, timeouts, and lifecycle hooks.
    """

    def __init__(self, middlewares: list["MiddlewareBase"]):
        self.middlewares = self._topological_sort(middlewares)

    def _topological_sort(self, middlewares: list["MiddlewareBase"]) -> list["MiddlewareBase"]:
        """Sort by dependencies using Kahn's algorithm, priority as tiebreaker."""
        if not middlewares:
            return []

        # Build name -> middleware mapping
        by_name = {m.__class__.__name__: m for m in middlewares}

        # Build dependency graph
        in_degree: dict[str, int] = defaultdict(int)
        dependents: dict[str, list[str]] = defaultdict(list)

        for m in middlewares:
            name = m.__class__.__name__
            in_degree[name]  # Ensure entry exists

            for dep in m.depends_on:
                if dep in by_name:
                    dependents[dep].append(name)
                    in_degree[name] += 1

            for before in m.runs_before:
                if before in by_name:
                    dependents[name].append(before)
                    in_degree[before] += 1

        # Kahn's algorithm with priority tiebreaker
        result: list["MiddlewareBase"] = []
        available = [m for m in middlewares if in_degree[m.__class__.__name__] == 0]

        while available:
            # Sort by priority (lower first)
            available.sort(key=lambda m: m.priority)
            current = available.pop(0)
            result.append(current)

            for dep_name in dependents[current.__class__.__name__]:
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    available.append(by_name[dep_name])

        if len(result) != len(middlewares):
            remaining = [m.__class__.__name__ for m in middlewares if m not in result]
            raise ValueError(
                f"Circular dependency detected in middleware chain. "
                f"Middleware involved: {remaining}"
            )

        return result

    def _apply_transform(self, current: T, result: R) -> T:
        """Apply transformation based on result type."""
        # Import here to avoid circular imports at module level
        from .results import EnrichmentResult, QueryProcessorResult

        if isinstance(result, EnrichmentResult) and result.action == "transform":
            return result.content if result.content is not None else current  # type: ignore
        elif isinstance(result, QueryProcessorResult) and result.action == "transform":
            return result.query if result.query is not None else current  # type: ignore
        return current

    async def execute(
        self,
        initial_value: T,
        context: "RequestContext",
        process_fn: str = "process"
    ) -> tuple[T, list[tuple[str, R]]]:
        """Execute middleware chain.

        Args:
            initial_value: Starting value to process
            context: Request context passed to all middleware
            process_fn: Name of the method to call on each middleware

        Returns:
            Tuple of (final_value, [(middleware_name, result), ...])
        """
        results: list[tuple[str, R]] = []
        current = initial_value
        success = True

        # Lifecycle: chain start
        for middleware in self.middlewares:
            try:
                await middleware.on_chain_start(context)
            except Exception as e:
                logger.warning(f"on_chain_start failed for {middleware.__class__.__name__}: {e}")

        try:
            for middleware in self.middlewares:
                name = middleware.__class__.__name__
                start_time = time.monotonic()

                try:
                    # Validate method exists and is async
                    method = getattr(middleware, process_fn, None)
                    if method is None:
                        raise MiddlewareError(
                            name, f"Missing required method '{process_fn}'"
                        )
                    if not asyncio.iscoroutinefunction(method):
                        raise MiddlewareError(
                            name, f"Method '{process_fn}' must be async"
                        )

                    # Apply timeout if configured
                    if middleware.timeout_seconds:
                        coro = method(current, context)
                        result = await asyncio.wait_for(coro, timeout=middleware.timeout_seconds)
                    else:
                        result = await method(current, context)

                    elapsed_ms = (time.monotonic() - start_time) * 1000

                    logger.info(
                        "middleware_executed",
                        extra={
                            "middleware": name,
                            "action": result.action,
                            "duration_ms": round(elapsed_ms, 2),
                            "request_id": context.request_id,
                        }
                    )

                    results.append((name, result))

                    if result.action == "reject":
                        raise MiddlewareRejection(name, result.reason)
                    elif result.action == "transform":
                        current = self._apply_transform(current, result)

                except MiddlewareRejection:
                    success = False
                    raise
                except asyncio.TimeoutError:
                    logger.error(
                        "middleware_timeout",
                        extra={
                            "middleware": name,
                            "timeout_seconds": middleware.timeout_seconds,
                            "request_id": context.request_id,
                        }
                    )
                    if middleware.on_error == "reject":
                        success = False
                        raise MiddlewareError(name, f"Timeout after {middleware.timeout_seconds}s")
                    elif middleware.on_error == "skip":
                        continue
                    # on_error == "allow": continue with current value
                except Exception as e:
                    if isinstance(e, (MiddlewareError, MiddlewareRejection)):
                        raise

                    logger.error(
                        "middleware_error",
                        extra={
                            "middleware": name,
                            "error": str(e),
                            "request_id": context.request_id,
                        }
                    )
                    if middleware.on_error == "reject":
                        success = False
                        raise MiddlewareError(name, str(e))
                    elif middleware.on_error == "skip":
                        continue
                    # on_error == "allow": continue with current value

        finally:
            # Lifecycle: chain complete
            for middleware in self.middlewares:
                try:
                    await middleware.on_chain_complete(context, success)
                except Exception as e:
                    logger.warning(f"on_chain_complete failed for {middleware.__class__.__name__}: {e}")

        return current, results
