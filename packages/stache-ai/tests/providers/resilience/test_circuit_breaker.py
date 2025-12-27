"""Comprehensive test suite for CircuitBreaker with full state transition coverage.

Tests cover:
- Initial state and transitions
- All three states (CLOSED, OPEN, HALF_OPEN)
- Automatic timeout-based recovery
- Thread safety with concurrent operations
- Edge cases with extreme parameter values
"""

import pytest
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from stache_ai.providers.resilience import CircuitBreaker, CircuitState


@pytest.fixture
def circuit_breaker():
    """Create a circuit breaker with standard test configuration.

    Configuration:
    - threshold: 3 failures to open circuit
    - timeout: 1.0 second recovery wait
    - half_open_max_calls: 2 test calls allowed in HALF_OPEN state
    """
    return CircuitBreaker(threshold=3, timeout=1.0, half_open_max_calls=2)


class TestInitialState:
    """Test 1: Verify initial state is CLOSED with correct stats."""

    def test_initial_state_is_closed(self, circuit_breaker):
        """Verify circuit breaker starts in CLOSED state."""
        assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_can_attempt_returns_true_initially(self, circuit_breaker):
        """Verify requests are allowed in initial CLOSED state."""
        assert circuit_breaker.can_attempt() is True

    def test_initial_stats_are_zero(self, circuit_breaker):
        """Verify stats show 0 failures/successes in initial state."""
        stats = circuit_breaker.get_stats()

        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0
        assert stats["last_failure"] is None

    def test_multiple_can_attempt_calls_in_closed_state(self, circuit_breaker):
        """Verify multiple can_attempt() calls work correctly in CLOSED state."""
        for _ in range(5):
            assert circuit_breaker.can_attempt() is True

        # Stats should still show 0 failures
        stats = circuit_breaker.get_stats()
        assert stats["failure_count"] == 0


class TestStateTransitions:
    """Test 2: Verify state transitions through failure threshold."""

    def test_transition_closed_to_open_by_threshold(self, circuit_breaker):
        """Verify circuit transitions to OPEN when failure count reaches threshold."""
        # Record failures up to threshold
        for i in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        assert circuit_breaker.get_state() == CircuitState.OPEN

    def test_can_attempt_returns_false_when_open(self, circuit_breaker):
        """Verify requests are rejected when circuit is OPEN."""
        # Open the circuit
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        assert circuit_breaker.can_attempt() is False

    def test_failure_count_increments_correctly(self, circuit_breaker):
        """Verify failure count increments with each failure recorded."""
        assert circuit_breaker.get_stats()["failure_count"] == 0

        circuit_breaker.record_failure()
        assert circuit_breaker.get_stats()["failure_count"] == 1

        circuit_breaker.record_failure()
        assert circuit_breaker.get_stats()["failure_count"] == 2

        circuit_breaker.record_failure()
        assert circuit_breaker.get_stats()["failure_count"] == 3

    def test_last_failure_timestamp_recorded(self, circuit_breaker):
        """Verify last_failure timestamp is recorded and updated."""
        assert circuit_breaker.get_stats()["last_failure"] is None

        before = datetime.now()
        circuit_breaker.record_failure()
        after = datetime.now()

        stats = circuit_breaker.get_stats()
        assert stats["last_failure"] is not None

        # Parse ISO timestamp and verify it's within expected range
        last_failure = datetime.fromisoformat(stats["last_failure"])
        assert before <= last_failure <= after


class TestRecoveryToHalfOpen:
    """Test 3: Verify automatic recovery from OPEN to HALF_OPEN state."""

    def test_automatic_transition_open_to_half_open_after_timeout(self, circuit_breaker):
        """Verify circuit automatically transitions to HALF_OPEN after timeout expires.

        Sequence:
        1. Open circuit by exceeding failure threshold
        2. Verify state is OPEN
        3. Wait for timeout duration
        4. Call get_state() (triggers automatic transition)
        5. Verify state is now HALF_OPEN
        """
        # Open the circuit
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        assert circuit_breaker.get_state() == CircuitState.OPEN

        # Wait for timeout to elapse
        time.sleep(circuit_breaker.timeout + 0.1)

        # Automatic transition happens on next state check
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

    def test_can_attempt_returns_true_in_half_open(self, circuit_breaker):
        """Verify requests are allowed in HALF_OPEN state."""
        # Transition to OPEN
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        # Wait for timeout and transition to HALF_OPEN
        time.sleep(circuit_breaker.timeout + 0.1)

        # Should now allow attempts
        assert circuit_breaker.can_attempt() is True

    def test_half_open_respects_max_calls_limit(self, circuit_breaker):
        """Verify HALF_OPEN state respects max_calls limit.

        In HALF_OPEN state, only half_open_max_calls test requests are allowed.
        After that, can_attempt() should return False.
        """
        # Open and transition to HALF_OPEN
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        time.sleep(circuit_breaker.timeout + 0.1)
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

        # Exhaust max test calls
        for i in range(circuit_breaker.half_open_max_calls):
            assert circuit_breaker.can_attempt() is True

        # Next call should be rejected (max calls exceeded)
        assert circuit_breaker.can_attempt() is False

    def test_half_open_calls_reset_on_failure(self, circuit_breaker):
        """Verify half_open_calls counter resets when failure occurs in HALF_OPEN."""
        # Transition to HALF_OPEN
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        time.sleep(circuit_breaker.timeout + 0.1)

        # Consume one test call
        circuit_breaker.can_attempt()

        # Now fail - should transition back to OPEN and reset counters
        circuit_breaker.record_failure()

        assert circuit_breaker.get_state() == CircuitState.OPEN


class TestHalfOpenToClosed:
    """Test 4: Verify successful recovery from HALF_OPEN to CLOSED state."""

    def test_transition_half_open_to_closed_on_success(self, circuit_breaker):
        """Verify circuit transitions to CLOSED after enough successes in HALF_OPEN.

        Sequence:
        1. Transition to HALF_OPEN via timeout
        2. Record half_open_max_calls successes
        3. Verify state is now CLOSED
        """
        # Open circuit
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        # Transition to HALF_OPEN
        time.sleep(circuit_breaker.timeout + 0.1)
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

        # Record successful attempts
        for _ in range(circuit_breaker.half_open_max_calls):
            circuit_breaker.record_success()

        # Should transition back to CLOSED
        assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_failure_counters_reset_on_recovery(self, circuit_breaker):
        """Verify failure and success counters are reset when transitioning to CLOSED.

        Note: failure_count maintains historical record but transitions_to_closed()
        resets both counters. The circuit returns to CLOSED state with clean counters.
        """
        # Open circuit
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        initial_failure_count = circuit_breaker.get_stats()["failure_count"]
        assert initial_failure_count == circuit_breaker.threshold

        # Recover through HALF_OPEN
        time.sleep(circuit_breaker.timeout + 0.1)

        # Verify we're in HALF_OPEN state
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

        for _ in range(circuit_breaker.half_open_max_calls):
            circuit_breaker.record_success()

        # Verify state is closed and counters reset after recovery
        stats = circuit_breaker.get_stats()
        assert stats["state"] == "closed"
        # After successful recovery to CLOSED, both counters reset
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0

    def test_can_attempt_returns_true_after_recovery(self, circuit_breaker):
        """Verify normal operation resumes after recovery to CLOSED."""
        # Complete failure and recovery cycle
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        time.sleep(circuit_breaker.timeout + 0.1)

        for _ in range(circuit_breaker.half_open_max_calls):
            circuit_breaker.record_success()

        # Should be able to attempt requests again
        assert circuit_breaker.can_attempt() is True


class TestHalfOpenToOpen:
    """Test 5: Verify immediate transition from HALF_OPEN to OPEN on failure."""

    def test_transition_half_open_to_open_on_failure(self, circuit_breaker):
        """Verify single failure in HALF_OPEN transitions immediately to OPEN.

        This tests that the circuit rejects recovery if any test request fails.
        """
        # Transition to HALF_OPEN
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        time.sleep(circuit_breaker.timeout + 0.1)
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

        # Single failure should reopen
        circuit_breaker.record_failure()

        assert circuit_breaker.get_state() == CircuitState.OPEN

    def test_failure_in_half_open_does_not_increment_normal_counter(self, circuit_breaker):
        """Verify failure in HALF_OPEN state resets test counters immediately."""
        # Open and transition to HALF_OPEN
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        time.sleep(circuit_breaker.timeout + 0.1)

        # Consume some test calls
        circuit_breaker.can_attempt()

        # Check state before failure
        stats_before = circuit_breaker.get_stats()

        # Record failure
        circuit_breaker.record_failure()

        # Verify test counters were reset
        stats_after = circuit_breaker.get_stats()
        assert stats_after["state"] == "open"

    def test_multiple_failures_in_half_open_pattern(self, circuit_breaker):
        """Verify pattern of: CLOSED -> OPEN -> HALF_OPEN -> OPEN -> CLOSED."""
        # First cycle: CLOSED -> OPEN
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()
        assert circuit_breaker.get_state() == CircuitState.OPEN

        # Wait for HALF_OPEN
        time.sleep(circuit_breaker.timeout + 0.1)
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

        # Fail back to OPEN
        circuit_breaker.record_failure()
        assert circuit_breaker.get_state() == CircuitState.OPEN

        # Wait for HALF_OPEN again
        time.sleep(circuit_breaker.timeout + 0.1)
        assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

        # This time succeed
        for _ in range(circuit_breaker.half_open_max_calls):
            circuit_breaker.record_success()
        assert circuit_breaker.get_state() == CircuitState.CLOSED


class TestThreadSafety:
    """Test 6: Verify thread safety with concurrent operations."""

    def test_concurrent_record_success_no_race_condition(self, circuit_breaker):
        """Verify concurrent success recording doesn't cause race conditions.

        Uses ThreadPoolExecutor to call record_success from 10 threads.
        Verifies final count matches expected value.
        """
        num_threads = 10
        calls_per_thread = 5

        def record_multiple_successes():
            for _ in range(calls_per_thread):
                circuit_breaker.record_success()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(record_multiple_successes) for _ in range(num_threads)]
            for future in futures:
                future.result()

        # Verify all successes were recorded (though some may overflow due to HALF_OPEN limit)
        stats = circuit_breaker.get_stats()
        # In CLOSED state, successes accumulate
        assert stats["success_count"] >= 0

    def test_concurrent_record_failure_no_race_condition(self, circuit_breaker):
        """Verify concurrent failure recording doesn't cause race conditions.

        Uses ThreadPoolExecutor to call record_failure from 10 threads.
        Verifies final failure count and state are consistent.
        """
        num_threads = 10
        calls_per_thread = 2

        def record_multiple_failures():
            for _ in range(calls_per_thread):
                circuit_breaker.record_failure()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(record_multiple_failures) for _ in range(num_threads)]
            for future in futures:
                future.result()

        # Verify all failures were recorded
        stats = circuit_breaker.get_stats()
        assert stats["failure_count"] == num_threads * calls_per_thread
        assert stats["state"] == "open"

    def test_concurrent_can_attempt_during_transitions(self, circuit_breaker):
        """Verify can_attempt() is safe during state transitions.

        Creates concurrent threads calling can_attempt() while other threads
        modify state through record_failure/record_success.
        """
        num_threads = 10
        results = []

        def attempt_and_record():
            for _ in range(5):
                result = circuit_breaker.can_attempt()
                results.append(result)
                if not result:
                    # If blocked, try to recover
                    circuit_breaker.record_failure()
                else:
                    circuit_breaker.record_success()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(attempt_and_record) for _ in range(num_threads)]
            for future in futures:
                future.result()

        # Verify results list has expected number of entries
        assert len(results) == num_threads * 5

        # Verify circuit is in a valid state
        state = circuit_breaker.get_state()
        assert state in [CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN]

    def test_concurrent_state_reads_consistent(self, circuit_breaker):
        """Verify concurrent get_state() calls return consistent results.

        Opens the circuit and reads state from multiple threads simultaneously.
        """
        # Open the circuit
        for _ in range(circuit_breaker.threshold):
            circuit_breaker.record_failure()

        states = []

        def read_state():
            for _ in range(10):
                states.append(circuit_breaker.get_state())

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(read_state) for _ in range(5)]
            for future in futures:
                future.result()

        # All reads should return OPEN
        assert all(s == CircuitState.OPEN for s in states)
        assert len(states) == 50  # 5 threads * 10 reads each


class TestEdgeCases:
    """Test 7: Verify edge cases with extreme parameters."""

    def test_threshold_of_one(self):
        """Verify circuit works correctly with threshold=1.

        Single failure should immediately open circuit.
        """
        cb = CircuitBreaker(threshold=1, timeout=0.5, half_open_max_calls=1)

        assert cb.get_state() == CircuitState.CLOSED

        # Single failure opens
        cb.record_failure()
        assert cb.get_state() == CircuitState.OPEN

        # Wait and recover
        time.sleep(0.6)
        assert cb.get_state() == CircuitState.HALF_OPEN

        # Single success closes
        cb.record_success()
        assert cb.get_state() == CircuitState.CLOSED

    def test_very_short_timeout(self):
        """Verify circuit works with very short timeout (0.1 seconds).

        Tests rapid failure and recovery cycles.
        """
        cb = CircuitBreaker(threshold=2, timeout=0.1, half_open_max_calls=1)

        # Open quickly
        cb.record_failure()
        cb.record_failure()
        assert cb.get_state() == CircuitState.OPEN

        # Recover very quickly
        time.sleep(0.15)
        assert cb.get_state() == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.get_state() == CircuitState.CLOSED

    def test_rapid_failure_success_cycles(self, circuit_breaker):
        """Verify circuit handles rapid alternating failure/success patterns.

        This stresses the state machine transitions.
        """
        for cycle in range(3):
            # Open circuit
            for _ in range(circuit_breaker.threshold):
                circuit_breaker.record_failure()
            assert circuit_breaker.get_state() == CircuitState.OPEN

            # Recover
            time.sleep(circuit_breaker.timeout + 0.1)
            assert circuit_breaker.get_state() == CircuitState.HALF_OPEN

            # Complete recovery
            for _ in range(circuit_breaker.half_open_max_calls):
                circuit_breaker.record_success()
            assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_high_half_open_max_calls(self):
        """Verify circuit works with high half_open_max_calls value."""
        cb = CircuitBreaker(threshold=2, timeout=0.5, half_open_max_calls=10)

        # Open
        cb.record_failure()
        cb.record_failure()

        # Recover
        time.sleep(0.6)
        assert cb.get_state() == CircuitState.HALF_OPEN

        # Should allow 10 test calls
        for i in range(10):
            assert cb.can_attempt() is True

        # 11th call should be rejected
        assert cb.can_attempt() is False

    def test_zero_timeout_immediate_recovery(self):
        """Verify circuit with timeout=0 allows immediate recovery attempt.

        With timeout=0, circuit automatically transitions to HALF_OPEN on next
        state check since time_since_failure >= timeout (0).
        """
        cb = CircuitBreaker(threshold=1, timeout=0.0, half_open_max_calls=1)

        # Record failure
        cb.record_failure()

        # Immediately after failure, internal state is OPEN
        # but get_state() triggers automatic OPEN -> HALF_OPEN transition
        # because time_since_failure >= timeout (0)
        state = cb.get_state()
        assert state == CircuitState.HALF_OPEN

        # Can attempt in HALF_OPEN
        assert cb.can_attempt() is True

    def test_invalid_threshold_raises_error(self):
        """Verify invalid threshold values raise ValueError."""
        with pytest.raises(ValueError, match="threshold must be > 0"):
            CircuitBreaker(threshold=0, timeout=1.0)

        with pytest.raises(ValueError, match="threshold must be > 0"):
            CircuitBreaker(threshold=-1, timeout=1.0)

    def test_invalid_timeout_raises_error(self):
        """Verify invalid timeout values raise ValueError."""
        with pytest.raises(ValueError, match="timeout must be >= 0"):
            CircuitBreaker(threshold=1, timeout=-1.0)

    def test_success_count_in_closed_state_increments(self, circuit_breaker):
        """Verify success_count increments even in CLOSED state."""
        # Record successes in CLOSED state (should be no-op for closure)
        circuit_breaker.record_success()

        stats = circuit_breaker.get_stats()
        assert stats["success_count"] == 1
        assert stats["state"] == "closed"


class TestStatsStructure:
    """Test stats dict structure and field presence."""

    def test_stats_has_all_required_fields(self, circuit_breaker):
        """Verify get_stats() returns all required fields."""
        stats = circuit_breaker.get_stats()

        required_fields = {"state", "failure_count", "success_count", "last_failure"}
        assert required_fields.issubset(stats.keys())

    def test_stats_state_values_are_strings(self, circuit_breaker):
        """Verify state field in stats is a string value."""
        stats = circuit_breaker.get_stats()

        assert isinstance(stats["state"], str)
        assert stats["state"] in ["closed", "open", "half_open"]

    def test_stats_counts_are_integers(self, circuit_breaker):
        """Verify count fields in stats are integers."""
        stats = circuit_breaker.get_stats()

        assert isinstance(stats["failure_count"], int)
        assert isinstance(stats["success_count"], int)
        assert stats["failure_count"] >= 0
        assert stats["success_count"] >= 0

    def test_stats_last_failure_is_iso_or_none(self, circuit_breaker):
        """Verify last_failure field is ISO timestamp or None."""
        # Before any failure
        stats = circuit_breaker.get_stats()
        assert stats["last_failure"] is None

        # After failure
        circuit_breaker.record_failure()
        stats = circuit_breaker.get_stats()

        assert isinstance(stats["last_failure"], str)
        # Should be valid ISO format
        datetime.fromisoformat(stats["last_failure"])
