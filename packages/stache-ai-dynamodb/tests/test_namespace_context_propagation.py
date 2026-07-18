"""Context-propagation tests for DynamoDBNamespaceProvider.

These tests prove that ``context`` is FORWARDED into every nested/sibling
data call - not merely accepted as a parameter. A sentinel object is passed
into the outer method and the spy on the nested method asserts it received
the exact same object (identity).

Regression guard for the isolation-critical forwarding defects (C1/C2/M1).
"""
from unittest.mock import MagicMock, call

import pytest

from stache_ai_dynamodb.namespace import DynamoDBNamespaceProvider

# Distinct sentinel standing in for a live RequestContext. The provider only
# forwards it; it never inspects it, so identity is all we assert.
CTX = object()


def _provider():
    """Build a provider without touching boto3/__init__."""
    prov = DynamoDBNamespaceProvider.__new__(DynamoDBNamespaceProvider)
    prov.table = MagicMock()
    return prov


def test_get_tree_forwards_context_into_list():
    prov = _provider()
    prov.list = MagicMock(return_value=[])

    prov.get_tree(context=CTX)

    prov.list.assert_called_once_with(include_children=True, context=CTX)


def test_delete_cascade_forwards_context_into_list_and_recursion(monkeypatch):
    prov = _provider()
    prov.exists = MagicMock(return_value=True)
    # parent has one child; child has none
    prov.list = MagicMock(
        side_effect=lambda parent_id=None, context=None: (
            [{"id": "child"}] if parent_id == "parent" else []
        )
    )

    recorded = []
    real_delete = DynamoDBNamespaceProvider.delete

    def recording_delete(self, id, cascade=False, context=None):
        recorded.append((id, context))
        return real_delete(self, id, cascade=cascade, context=context)

    monkeypatch.setattr(DynamoDBNamespaceProvider, "delete", recording_delete)

    prov.delete("parent", cascade=True, context=CTX)

    # child-enumeration list forwarded context (both parent + child levels)
    for c in prov.list.call_args_list:
        assert c.kwargs["context"] is CTX
    # recursive delete of the child forwarded the same context object
    assert ("child", CTX) in recorded


def test_create_forwards_context_into_exists_and_get():
    prov = _provider()
    # parent exists (validation passes), new id does not (duplicate check passes)
    prov.exists = MagicMock(side_effect=lambda _id, context=None: _id == "parent")
    prov.get = MagicMock(return_value={"id": "child"})
    prov.table.put_item = MagicMock()

    prov.create(id="child", name="Child", parent_id="parent", context=CTX)

    prov.exists.assert_any_call("parent", context=CTX)  # parent validation
    prov.exists.assert_any_call("child", context=CTX)   # duplicate check
    prov.get.assert_called_once_with("child", context=CTX)  # post-write re-read


def test_update_forwards_context_into_get_and_exists():
    prov = _provider()
    prov.get = MagicMock(return_value={"metadata": {}})
    prov.exists = MagicMock(return_value=True)
    prov.table.update_item = MagicMock()

    prov.update("child", name="New", parent_id="parent", context=CTX)

    # existing read + post-write re-read both forwarded context
    for c in prov.get.call_args_list:
        assert c.kwargs["context"] is CTX
    prov.exists.assert_called_once_with("parent", context=CTX)  # parent validation
