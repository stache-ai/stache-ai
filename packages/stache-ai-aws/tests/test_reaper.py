"""The reaper Lambda entrypoint delegates to the core reap function."""

from unittest.mock import patch

from stache_ai_aws import reaper


def test_lambda_handler_wraps_reap_count():
    with patch("stache_ai_aws.reaper.reap_stuck_jobs", return_value=3):
        assert reaper.lambda_handler({}, None) == {"reaped": 3}
