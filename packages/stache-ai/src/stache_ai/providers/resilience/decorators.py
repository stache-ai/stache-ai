"""Resilience decorators for providers."""

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


def with_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    operation_name: str = "operation"
):
    """Decorator to add retry logic with exponential backoff to any function.

    Useful for database operations, SDK calls, or any operation that might
    fail transiently. Does NOT include circuit breaker (use HttpClient for that).

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds, doubles each retry (default: 0.5)
        max_delay: Maximum delay cap in seconds (default: 10.0)
        exceptions: Tuple of exception types to catch and retry (default: all)
        operation_name: Human-readable operation name for logging

    Example:
        from botocore.exceptions import ClientError

        @with_retry(
            max_retries=3,
            base_delay=1.0,
            exceptions=(ClientError,),
            operation_name="DynamoDB get_item"
        )
        def get_namespace(self, id: str):
            response = self.table.get_item(Key={'id': id})
            return response.get('Item')
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        logger.error(
                            f"{operation_name} failed after {max_retries} retries: {e}"
                        )
                        raise

                    # Exponential backoff with jitter
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = random.uniform(-0.5, 0.5) * delay
                    final_delay = max(0, delay + jitter)

                    logger.info(
                        f"{operation_name} attempt {attempt + 1}/{max_retries + 1} "
                        f"failed: {e}. Retrying in {final_delay:.2f}s..."
                    )
                    time.sleep(final_delay)

            # This should never be reached, but satisfy type checker
            raise RuntimeError(f"{operation_name} failed unexpectedly")

        return wrapper
    return decorator
