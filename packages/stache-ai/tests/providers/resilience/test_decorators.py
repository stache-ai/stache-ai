"""Comprehensive test suite for @with_retry decorator.

Tests cover:
- Basic retry logic (success on first attempt, after failures)
- Exponential backoff calculation and jitter
- Exception type filtering (retry only on specified types)
- Configuration options (max_retries, delays)
- Edge cases (zero retries, high retry counts)
"""

import time

import pytest

from stache_ai.providers.resilience import with_retry


class TestBasicRetryLogic:
    """Test 1-3: Verify basic retry behavior."""

    def test_successful_execution_no_retry_needed(self):
        """Test that function returning successfully doesn't trigger retries."""
        call_count = 0

        @with_retry(max_retries=3)
        def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_function()

        assert result == "success"
        assert call_count == 1  # Called once, no retries needed

    def test_retry_after_single_failure(self):
        """Test that function retries once after single failure then succeeds."""
        call_count = 0

        @with_retry(max_retries=3)
        def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Transient error on first attempt")
            return "success on retry"

        result = flaky_function()

        assert result == "success on retry"
        assert call_count == 2  # Failed once, succeeded on first retry

    def test_retry_until_max_retries_exhausted(self):
        """Test that function exhausts max_retries and raises final exception."""
        call_count = 0
        max_retries = 3

        @with_retry(max_retries=max_retries)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Failure #{call_count}")

        with pytest.raises(ValueError, match="Failure #4"):
            always_fails()

        # Should have tried max_retries + 1 times (initial + 3 retries)
        assert call_count == max_retries + 1


class TestExponentialBackoff:
    """Test 4-5: Verify exponential backoff with jitter."""

    def test_exponential_backoff_delay_calculation(self):
        """Test that delays follow exponential backoff pattern: base_delay * 2^attempt."""
        call_count = 0
        call_times = []

        @with_retry(
            max_retries=3,
            base_delay=0.05,  # Small base for test speed
            max_delay=1.0
        )
        def fails_twice():
            nonlocal call_count
            call_count += 1
            call_times.append(time.time())
            if call_count <= 2:
                raise ValueError("Will retry")
            return "success"

        result = fails_twice()

        assert result == "success"
        assert call_count == 3  # Called 3 times total (2 failures + 1 success)
        assert len(call_times) == 3

        # Verify delays between calls are approximately exponential
        # Note: With jitter, we can't be exact, so we check ranges
        # Delay 1: should be ~0.05 * 2^0 = 0.05 (but with jitter, roughly 0.025-0.075)
        delay1 = call_times[1] - call_times[0]
        assert 0.01 < delay1 < 0.15  # Allow wide range for jitter

        # Delay 2: should be ~0.05 * 2^1 = 0.1 (but with jitter, roughly 0.05-0.15)
        delay2 = call_times[2] - call_times[1]
        assert 0.03 < delay2 < 0.25  # Allow wide range for jitter

        # Verify second delay is generally longer than first
        assert delay2 > delay1 * 0.5  # Allow jitter, but generally increasing

    def test_jitter_adds_randomness_to_delays(self):
        """Test that jitter causes delay variations across multiple retries."""
        delays_observed = []

        for trial in range(5):
            call_count = 0

            @with_retry(
                max_retries=2,
                base_delay=0.05,
                max_delay=1.0
            )
            def flaky_operation():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ValueError("Will retry")
                return "success"

            start = time.time()
            flaky_operation()
            elapsed = time.time() - start

            delays_observed.append(elapsed)

        # With jitter, delays should vary across trials
        # If no jitter, delays would be identical
        delay_min = min(delays_observed)
        delay_max = max(delays_observed)
        delay_range = delay_max - delay_min

        # Allow some variation (more than 1ms difference indicates jitter working)
        assert delay_range > 0.001, "Jitter should cause measurable variation"


class TestExceptionTypeFiltering:
    """Test 6-7: Verify exception type filtering."""

    def test_retry_only_on_specified_exception_types(self):
        """Test that decorator only retries on configured exception types."""
        call_count = 0

        @with_retry(
            max_retries=3,
            exceptions=(ValueError, TypeError)
        )
        def fails_with_specified_exception():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("This should be retried")
            return "success"

        result = fails_with_specified_exception()

        assert result == "success"
        assert call_count == 2  # Retried because ValueError is in exceptions list

    def test_do_not_retry_on_non_specified_exceptions(self):
        """Test that decorator does NOT retry on unspecified exception types."""
        call_count = 0

        @with_retry(
            max_retries=3,
            exceptions=(ValueError, TypeError)  # Only these types are retried
        )
        def fails_with_unspecified_exception():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("This exception type is NOT in retry list")

        with pytest.raises(RuntimeError, match="This exception type is NOT in retry list"):
            fails_with_unspecified_exception()

        # Should fail immediately without retry
        assert call_count == 1

    def test_custom_exception_type_list(self):
        """Test decorator with custom exception types (e.g., network errors)."""
        class NetworkError(Exception):
            pass

        class DatabaseError(Exception):
            pass

        call_count = 0

        @with_retry(
            max_retries=2,
            exceptions=(NetworkError, DatabaseError)
        )
        def api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise NetworkError("Connection timeout")
            if call_count == 2:
                raise DatabaseError("Connection pool exhausted")
            return "data"

        result = api_call()

        assert result == "data"
        assert call_count == 3  # Failed twice (both retryable), succeeded third time


class TestConfigurationOptions:
    """Test 8-9: Verify configuration flexibility."""

    def test_custom_max_retries_value(self):
        """Test that custom max_retries setting is respected."""
        call_count = 0
        custom_max_retries = 5

        @with_retry(max_retries=custom_max_retries)
        def fails_every_time():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Attempt {call_count}")

        with pytest.raises(ValueError):
            fails_every_time()

        # Should have exactly max_retries + 1 attempts
        assert call_count == custom_max_retries + 1

    def test_custom_base_delay_and_max_delay(self):
        """Test that base_delay and max_delay affect timing."""
        call_count = 0

        @with_retry(
            max_retries=3,
            base_delay=0.02,  # Very small base delay
            max_delay=0.05    # Tight max delay cap
        )
        def flaky_with_custom_delays():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("Retry me")
            return "done"

        start = time.time()
        result = flaky_with_custom_delays()
        elapsed = time.time() - start

        assert result == "done"
        # With base_delay=0.02 and max_delay=0.05, total time should be minimal
        # 0.02 * 2^0 ≈ 0.02, then 0.02 * 2^1 = 0.04, but capped at 0.05
        # Plus jitter, should still be under 0.3 seconds
        assert elapsed < 0.3


class TestEdgeCases:
    """Test 10: Verify behavior with edge case configurations."""

    def test_zero_retries_fails_immediately(self):
        """Test that max_retries=0 means no retries, fail on first error."""
        call_count = 0

        @with_retry(max_retries=0)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("No retries allowed")

        with pytest.raises(ValueError):
            always_fails()

        # Should fail immediately without any retries
        assert call_count == 1

    def test_very_high_max_retries(self):
        """Test behavior with very high max_retries value."""
        call_count = 0
        high_retries = 100

        @with_retry(max_retries=high_retries)
        def succeeds_on_tenth_try():
            nonlocal call_count
            call_count += 1
            if call_count < 10:
                raise ValueError("Try again")
            return "finally success"

        result = succeeds_on_tenth_try()

        assert result == "finally success"
        assert call_count == 10  # Stopped at 10, didn't need all 100 retries

    def test_max_delay_caps_exponential_backoff(self):
        """Test that max_delay prevents exponential delays from growing unbounded."""
        call_count = 0
        max_delay = 0.1  # Cap at 100ms

        @with_retry(
            max_retries=5,
            base_delay=0.2,
            max_delay=max_delay
        )
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                raise ValueError("Retry")
            return "success"

        start = time.time()
        result = fails_then_succeeds()
        elapsed = time.time() - start

        assert result == "success"
        # Without max_delay cap: 0.2 + 0.4 + 0.8 + 1.6 = 3.0+ seconds
        # With max_delay=0.1 cap: 0.1 + 0.1 + 0.1 + 0.1 = 0.4 seconds (plus jitter)
        # Should be significantly less than uncapped version
        assert elapsed < 0.8, "max_delay should cap exponential growth"


class TestDecoratorWithLogging:
    """Additional tests for logging behavior and decorator integration."""

    def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves original function's __name__ and __doc__."""
        @with_retry(max_retries=2)
        def documented_function():
            """This is a documented function."""
            return "value"

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a documented function."

    def test_decorator_works_with_function_arguments(self):
        """Test that decorator works with functions that have parameters."""
        call_count = 0

        @with_retry(max_retries=2)
        def function_with_args(a, b, c=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First attempt fails")
            return a + b + (c or 0)

        result = function_with_args(1, 2, c=3)

        assert result == 6
        assert call_count == 2

    def test_decorator_with_keyword_only_arguments(self):
        """Test that decorator works with keyword-only arguments."""
        call_count = 0

        @with_retry(max_retries=1)
        def function_with_kwargs(*, required_kwarg, optional_kwarg="default"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Retry")
            return f"{required_kwarg}-{optional_kwarg}"

        result = function_with_kwargs(
            required_kwarg="test",
            optional_kwarg="custom"
        )

        assert result == "test-custom"
        assert call_count == 2
