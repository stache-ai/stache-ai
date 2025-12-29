"""Circuit breaker for Ollama service resilience (core logic without thread safety).

This module implements the circuit breaker pattern to prevent cascading failures
when the Ollama service is unavailable or degraded. The circuit breaker tracks
failure patterns and transitions between three states:

- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures detected, reject requests immediately
- HALF_OPEN: Testing if service recovered, allow limited test requests

Thread safety is handled by the caller or implemented in a wrapper.
"""

import logging
import threading
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states.

    States:
        CLOSED: Normal operation, requests pass through
        OPEN: Failures exceeded threshold, reject requests
        HALF_OPEN: Testing if service recovered after timeout
    """
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failures exceeded threshold, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures when Ollama is down.

    State Machine:
        CLOSED -> (failure_count >= threshold) -> OPEN
        OPEN -> (timeout elapsed) -> HALF_OPEN
        HALF_OPEN -> (success_count >= half_open_max_calls) -> CLOSED
        HALF_OPEN -> (any failure) -> OPEN

    Configuration:
        threshold: Number of failures before opening circuit
        timeout: Seconds to wait before transitioning to half-open
        half_open_max_calls: Max test calls allowed in half-open state
    """

    def __init__(
        self,
        threshold: int,
        timeout: float,
        half_open_max_calls: int = 3
    ):
        """Initialize circuit breaker.

        Args:
            threshold: Number of failures required to open circuit
            timeout: Seconds to wait in OPEN state before trying HALF_OPEN
            half_open_max_calls: Maximum test calls in HALF_OPEN state (default: 3)

        Raises:
            ValueError: If threshold <= 0 or timeout < 0
        """
        if threshold <= 0:
            raise ValueError("threshold must be > 0")
        if timeout < 0:
            raise ValueError("timeout must be >= 0")

        self.threshold = threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls

        # Core state tracking
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._half_open_calls = 0

        # Thread safety
        self._lock = threading.Lock()

    def _get_current_state(self) -> CircuitState:
        """Get current state, handling automatic OPEN -> HALF_OPEN transition.

        This method automatically transitions the circuit from OPEN to HALF_OPEN
        when the recovery timeout has elapsed. This allows the circuit to test
        if the service has recovered without waiting for an explicit timeout check.

        NOTE: This method must be called with self._lock held.

        Returns:
            Current circuit state (may transition OPEN -> HALF_OPEN)

        State Transition Logic:
            - If state is OPEN and (now - last_failure_time) >= timeout:
              Transition to HALF_OPEN and reset test counters
            - Otherwise: return current state unchanged
        """
        if self._state == CircuitState.OPEN and self._last_failure_time:
            time_since_failure = datetime.now() - self._last_failure_time

            if time_since_failure.total_seconds() >= self.timeout:
                logger.info(
                    f"Circuit breaker transitioning to HALF_OPEN "
                    f"after {time_since_failure.total_seconds():.1f}s timeout"
                )
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0

        return self._state

    def _transition_to_closed(self):
        """Transition to CLOSED state (recovery complete).

        Resets all failure and success counters to initial state.
        This method must be called with self._lock held.
        """
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        logger.info("Circuit breaker transitioned to CLOSED (recovery complete)")

    def can_attempt(self) -> bool:
        """Check if request should be attempted (thread-safe).

        Determines whether the circuit breaker allows a request attempt based on
        current state. In HALF_OPEN state, tracks test call count.

        Returns:
            True if request should be attempted, False if circuit is OPEN
        """
        with self._lock:
            current_state = self._get_current_state()

            if current_state == CircuitState.OPEN:
                logger.warning("Circuit breaker OPEN - rejecting request")
                return False

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    logger.debug(
                        f"HALF_OPEN max test calls ({self.half_open_max_calls}) "
                        f"exceeded, rejecting request"
                    )
                    return False
                self._half_open_calls += 1
                logger.debug(
                    f"Allowing HALF_OPEN test call {self._half_open_calls}/"
                    f"{self.half_open_max_calls}"
                )

            return True

    def record_success(self) -> None:
        """Record successful request (thread-safe).

        Increments success counter and transitions HALF_OPEN -> CLOSED if
        threshold is reached. In CLOSED state, this is a no-op.
        """
        with self._lock:
            self._success_count += 1
            logger.debug(f"Recorded success (count: {self._success_count})")

            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.half_open_max_calls:
                    self._transition_to_closed()

    def record_failure(self) -> None:
        """Record failed request (thread-safe).

        Increments failure counter and transitions states:
        - CLOSED -> OPEN if threshold is reached
        - HALF_OPEN -> OPEN immediately

        Resets half-open test counters and records failure timestamp.
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            self._half_open_calls = 0
            logger.debug(f"Recorded failure (count: {self._failure_count})")

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker transitioned to OPEN "
                    "(failure during HALF_OPEN recovery test)"
                )
            elif self._failure_count >= self.threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker transitioned to OPEN "
                    f"(failure count {self._failure_count} >= threshold {self.threshold})"
                )

    def get_state(self) -> CircuitState:
        """Get current circuit state (thread-safe).

        Returns:
            Current state, may transition OPEN -> HALF_OPEN if timeout elapsed
        """
        with self._lock:
            return self._get_current_state()

    def get_stats(self) -> dict:
        """Get circuit breaker statistics for monitoring (thread-safe).

        Returns:
            Dict with fields:
                state: Current state as string (closed, open, half_open)
                failure_count: Total failures recorded
                success_count: Successful attempts in HALF_OPEN state
                last_failure: ISO timestamp of last failure, or None
        """
        with self._lock:
            return {
                "state": self._get_current_state().value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None
            }
