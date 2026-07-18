"""Context-propagation tests for RedisNamespaceProvider.

Proves ``context`` is FORWARDED into every nested/sibling data call, not
merely accepted. Regression guard for C1/C2/M1.
"""
from unittest.mock import MagicMock

from stache_ai_redis.provider import RedisNamespaceProvider

CTX = object()


def _provider():
    prov = RedisNamespaceProvider.__new__(RedisNamespaceProvider)
    prov.client = MagicMock()
    return prov


def test_get_tree_forwards_context_into_list():
    prov = _provider()
    prov.list = MagicMock(return_value=[])

    prov.get_tree(context=CTX)

    prov.list.assert_called_once_with(include_children=True, context=CTX)


def test_delete_cascade_forwards_context_into_list_and_recursion(monkeypatch):
    prov = _provider()
    prov.exists = MagicMock(return_value=True)
    prov.list = MagicMock(
        side_effect=lambda parent_id=None, context=None: (
            [{"id": "child"}] if parent_id == "parent" else []
        )
    )

    recorded = []
    real_delete = RedisNamespaceProvider.delete

    def recording_delete(self, id, cascade=False, context=None):
        recorded.append((id, context))
        return real_delete(self, id, cascade=cascade, context=context)

    monkeypatch.setattr(RedisNamespaceProvider, "delete", recording_delete)

    prov.delete("parent", cascade=True, context=CTX)

    for c in prov.list.call_args_list:
        assert c.kwargs["context"] is CTX
    assert ("child", CTX) in recorded


def test_create_forwards_context_into_exists():
    prov = _provider()
    # new id does not exist (duplicate check passes); parent exists (validation passes)
    prov.exists = MagicMock(side_effect=lambda _id, context=None: _id == "parent")

    prov.create(id="child", name="Child", parent_id="parent", context=CTX)

    prov.exists.assert_any_call("child", context=CTX)   # duplicate check
    prov.exists.assert_any_call("parent", context=CTX)  # parent validation


def test_update_forwards_context_into_get_and_exists():
    prov = _provider()
    prov.get = MagicMock(return_value={"metadata": {}})
    prov.exists = MagicMock(return_value=True)

    prov.update("child", name="New", parent_id="parent", context=CTX)

    prov.get.assert_called_once_with("child", context=CTX)      # existing read
    prov.exists.assert_called_once_with("parent", context=CTX)  # parent validation
