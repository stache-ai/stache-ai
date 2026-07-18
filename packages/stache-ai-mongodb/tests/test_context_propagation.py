"""Context-propagation tests for the MongoDB providers.

Proves ``context`` is FORWARDED into every nested/sibling data call, not
merely accepted. A sentinel object is passed into the outer method and the
spy on the nested method asserts identity.

Regression guard for C1/C2/M1 (namespace) and H1 (document index).
"""
from unittest.mock import MagicMock

from stache_ai_mongodb.namespace import MongoDBNamespaceProvider
from stache_ai_mongodb.document_index import MongoDBDocumentIndex

CTX = object()


def _namespace_provider():
    prov = MongoDBNamespaceProvider.__new__(MongoDBNamespaceProvider)
    prov.collection = MagicMock()
    return prov


def _doc_index():
    prov = MongoDBDocumentIndex.__new__(MongoDBDocumentIndex)
    prov.collection = MagicMock()
    return prov


def test_get_tree_forwards_context_into_list():
    prov = _namespace_provider()
    prov.list = MagicMock(return_value=[])

    prov.get_tree(context=CTX)

    prov.list.assert_called_once_with(include_children=True, context=CTX)


def test_delete_cascade_forwards_context_into_recursion(monkeypatch):
    prov = _namespace_provider()
    prov.exists = MagicMock(return_value=True)
    # count_documents(parent) > 0 so cascade branch runs; find() yields one child
    prov.collection.count_documents = MagicMock(return_value=1)
    prov.collection.find = MagicMock(
        side_effect=lambda q: [{"_id": "child"}] if q == {"parent_id": "parent"} else []
    )
    prov.collection.delete_one = MagicMock()

    recorded = []
    real_delete = MongoDBNamespaceProvider.delete

    def recording_delete(self, id, cascade=False, context=None):
        recorded.append((id, context))
        return real_delete(self, id, cascade=cascade, context=context)

    monkeypatch.setattr(MongoDBNamespaceProvider, "delete", recording_delete)

    prov.delete("parent", cascade=True, context=CTX)

    assert ("child", CTX) in recorded  # recursive delete forwarded context


def test_create_forwards_context_into_exists_and_get():
    prov = _namespace_provider()
    # parent exists so validation passes
    prov.exists = MagicMock(side_effect=lambda _id, context=None: _id == "parent")
    prov.get = MagicMock(return_value={"id": "child"})
    prov.collection.insert_one = MagicMock()

    prov.create(id="child", name="Child", parent_id="parent", context=CTX)

    prov.exists.assert_called_once_with("parent", context=CTX)  # parent validation
    prov.get.assert_called_once_with("child", context=CTX)      # post-write re-read


def test_update_forwards_context_into_get_and_exists():
    prov = _namespace_provider()
    prov.get = MagicMock(return_value={"metadata": {}})
    prov.exists = MagicMock(return_value=True)
    prov.collection.update_one = MagicMock()

    prov.update("child", name="New", parent_id="parent", context=CTX)

    for c in prov.get.call_args_list:
        assert c.kwargs["context"] is CTX
    prov.exists.assert_called_once_with("parent", context=CTX)


def test_get_chunk_ids_forwards_context_into_get_document():
    prov = _doc_index()
    prov.get_document = MagicMock(return_value={"chunk_ids": ["a", "b"]})

    result = prov.get_chunk_ids("doc-1", "ns-1", context=CTX)

    assert result == ["a", "b"]
    prov.get_document.assert_called_once_with("doc-1", "ns-1", context=CTX)
