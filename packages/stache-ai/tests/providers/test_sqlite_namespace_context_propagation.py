"""Context-propagation tests for SQLiteNamespaceProvider.

Proves ``context`` is FORWARDED into every nested/sibling data call, not
merely accepted. Uses a real temp SQLite DB and spies (``wraps``) the nested
methods so the actual behavior runs while we assert on the forwarded object.

Regression guard for C1/C2/M1.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from stache_ai.providers.namespace.sqlite import SQLiteNamespaceProvider

CTX = object()


@pytest.fixture
def provider(tmp_path):
    settings = SimpleNamespace(namespace_db_path=str(tmp_path / "ns.db"))
    return SQLiteNamespaceProvider(settings)


def test_get_tree_forwards_context_into_list(provider):
    with patch.object(provider, "list", wraps=provider.list) as spy:
        provider.get_tree(context=CTX)
    spy.assert_called_once_with(include_children=True, context=CTX)


def test_create_forwards_context_into_exists_and_get(provider):
    provider.create(id="parent", name="Parent")
    with patch.object(provider, "exists", wraps=provider.exists) as ex, \
         patch.object(provider, "get", wraps=provider.get) as g:
        provider.create(id="child", name="Child", parent_id="parent", context=CTX)
    ex.assert_called_once_with("parent", context=CTX)  # parent validation
    g.assert_called_once_with("child", context=CTX)     # post-write re-read


def test_update_forwards_context_into_get_and_exists(provider):
    provider.create(id="parent", name="Parent")
    provider.create(id="child", name="Child", parent_id="parent")
    with patch.object(provider, "get", wraps=provider.get) as g, \
         patch.object(provider, "exists", wraps=provider.exists) as ex:
        provider.update("child", name="New", parent_id="parent", context=CTX)
    # existing read + post-write re-read both forwarded context
    for c in g.call_args_list:
        assert c.kwargs["context"] is CTX
    ex.assert_called_once_with("parent", context=CTX)  # parent validation


def test_delete_cascade_forwards_context_into_recursion(provider, monkeypatch):
    provider.create(id="parent", name="Parent")
    provider.create(id="child", name="Child", parent_id="parent")

    recorded = []
    real_delete = SQLiteNamespaceProvider.delete

    def recording_delete(self, id, cascade=False, context=None):
        recorded.append((id, context))
        return real_delete(self, id, cascade=cascade, context=context)

    monkeypatch.setattr(SQLiteNamespaceProvider, "delete", recording_delete)

    provider.delete("parent", cascade=True, context=CTX)

    # child was enumerated via raw SQL then deleted recursively with same context
    assert ("child", CTX) in recorded
    assert provider.exists("child") is False  # actually deleted
