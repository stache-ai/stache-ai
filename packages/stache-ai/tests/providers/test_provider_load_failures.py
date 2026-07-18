"""A provider that fails to import must not be reported as an unknown provider

Discovery deliberately tolerates an ImportError from a single entry point: a
provider whose optional dependency is not installed must not take down the
providers registered next to it. The bug is what came after -- the failure was
logged at DEBUG and then forgotten, so a provider that was *configured*, was
*installed*, and simply could not import came back from the factory as:

    Unknown embedding provider: acme. Available: fallback, bedrock

which is false, and sends the reader looking for a typo instead of at the
broken install. These tests pin the corrected behaviour.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from stache_ai.config import Settings
from stache_ai.providers import plugin_loader
from stache_ai.providers.factories import EmbeddingProviderFactory


BROKEN_IMPORT_ERROR = ModuleNotFoundError("No module named 'acme_sdk'")


def _entry_point(name, load_result=None, load_error=None):
    ep = MagicMock()
    ep.name = name
    if load_error is not None:
        ep.load.side_effect = load_error
    else:
        ep.load.return_value = load_result
    return ep


class TestProviderLoadFailures:
    """Discovery records what it skipped; the factory reports it."""

    def setup_method(self):
        plugin_loader.reset()

    def teardown_method(self):
        plugin_loader.reset()

    @staticmethod
    def _patch_entry_points(mock_eps, working_class):
        """One healthy provider, one whose module is missing."""
        mock_eps.return_value.select.return_value = [
            _entry_point('working', load_result=working_class),
            _entry_point('acme', load_error=BROKEN_IMPORT_ERROR),
        ]

    @patch('importlib.metadata.entry_points')
    def test_create_names_the_missing_module_not_unknown_provider(self, mock_eps):
        """(a) Explicitly requesting the broken provider names the real cause."""
        self._patch_entry_points(mock_eps, MagicMock())

        settings = MagicMock(spec=Settings)
        settings.embedding_provider = 'acme'

        with pytest.raises(ValueError) as exc_info:
            EmbeddingProviderFactory.create(settings)

        message = str(exc_info.value)
        assert "failed to load" in message
        assert "acme_sdk" in message           # the module that was missing
        assert "ModuleNotFoundError" in message
        assert "Unknown" not in message        # the old lie

        # ...and the original exception is chained, so the traceback still
        # carries the full import failure.
        assert exc_info.value.__cause__ is BROKEN_IMPORT_ERROR

    @patch('importlib.metadata.entry_points')
    def test_broken_provider_does_not_break_its_neighbours(self, mock_eps):
        """(b) Discovery of the other providers in the group still succeeds."""
        working_class = MagicMock()
        self._patch_entry_points(mock_eps, working_class)

        available = EmbeddingProviderFactory.get_available_providers()
        assert 'working' in available
        assert 'acme' not in available

        settings = MagicMock(spec=Settings)
        settings.embedding_provider = 'working'
        EmbeddingProviderFactory.create(settings)
        working_class.assert_called_once_with(settings)

    @patch('importlib.metadata.entry_points')
    def test_genuinely_unknown_name_still_says_unknown(self, mock_eps):
        """(c) A name in neither the registry nor the failures is still unknown."""
        self._patch_entry_points(mock_eps, MagicMock())

        settings = MagicMock(spec=Settings)
        settings.embedding_provider = 'typo'

        with pytest.raises(ValueError, match="Unknown embedding provider: typo"):
            EmbeddingProviderFactory.create(settings)

    @patch('importlib.metadata.entry_points')
    def test_failure_is_logged_at_warning(self, mock_eps, caplog):
        """(d) WARNING, not DEBUG -- deployments run at LOG_LEVEL=info."""
        self._patch_entry_points(mock_eps, MagicMock())

        with caplog.at_level(logging.WARNING, logger='stache_ai.providers.plugin_loader'):
            plugin_loader.get_providers('embeddings')

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any('acme' in r.getMessage() and 'acme_sdk' in r.getMessage()
                   for r in warnings), [r.getMessage() for r in warnings]

    @patch('importlib.metadata.entry_points')
    def test_get_load_failures_exposes_the_exception(self, mock_eps):
        """The introspection helper reports the group's recorded failures."""
        self._patch_entry_points(mock_eps, MagicMock())

        failures = plugin_loader.get_load_failures('embeddings')
        assert set(failures) == {'acme'}
        assert failures['acme'] is BROKEN_IMPORT_ERROR

        # Same answer via the raw entry point group name.
        assert set(plugin_loader.get_load_failures('stache.embeddings')) == {'acme'}

    @patch('importlib.metadata.entry_points')
    def test_reset_clears_recorded_failures(self, mock_eps):
        """reset() must clear failures too, or tests leak state into each other."""
        self._patch_entry_points(mock_eps, MagicMock())
        assert plugin_loader.get_load_failures('embeddings')

        plugin_loader.reset()
        assert plugin_loader._load_failures == {}
