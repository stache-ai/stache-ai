"""Namespace provider contract tests."""

import uuid
from abc import ABC, abstractmethod

import pytest


class NamespaceContractTest(ABC):
    """Base class for Namespace provider contract tests."""

    @pytest.fixture
    @abstractmethod
    def provider(self):
        """Create the provider instance under test."""
        pass

    @pytest.fixture
    def test_namespace_id(self) -> str:
        return f"test-ns-{uuid.uuid4().hex[:8]}"

    def test_create_returns_namespace(self, provider, test_namespace_id):
        """create() must return namespace dict with id."""
        ns = provider.create(
            id=test_namespace_id,
            name="Test Namespace",
            description="A test namespace"
        )

        assert isinstance(ns, dict)
        assert ns.get("id") == test_namespace_id
        assert "name" in ns

    def test_get_returns_namespace(self, provider, test_namespace_id):
        """get() must return namespace after creation."""
        provider.create(id=test_namespace_id, name="Test")

        ns = provider.get(test_namespace_id)

        assert ns is not None
        assert ns.get("id") == test_namespace_id

    def test_get_nonexistent_returns_none(self, provider):
        """get() must return None for nonexistent namespace."""
        ns = provider.get("nonexistent-namespace-12345")

        assert ns is None

    def test_exists_returns_boolean(self, provider, test_namespace_id):
        """exists() must return correct boolean."""
        assert provider.exists(test_namespace_id) is False

        provider.create(id=test_namespace_id, name="Test")

        assert provider.exists(test_namespace_id) is True

    def test_list_returns_list(self, provider, test_namespace_id):
        """list() must return list of namespaces."""
        provider.create(id=test_namespace_id, name="Test")

        namespaces = provider.list()

        assert isinstance(namespaces, list)

    def test_delete_removes_namespace(self, provider, test_namespace_id):
        """delete() must remove namespace."""
        provider.create(id=test_namespace_id, name="Test")

        result = provider.delete(test_namespace_id)

        assert result is True
        assert provider.exists(test_namespace_id) is False

    def test_update_modifies_namespace(self, provider, test_namespace_id):
        """update() must modify namespace fields."""
        provider.create(id=test_namespace_id, name="Original Name")

        updated = provider.update(id=test_namespace_id, name="New Name")

        assert updated is not None
        assert updated.get("name") == "New Name"
