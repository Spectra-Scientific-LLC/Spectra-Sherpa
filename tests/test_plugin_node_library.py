from __future__ import annotations

import pytest

from spectra_sherpa.app.api.v1.routes.workflows import get_node_library
from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, node_registry, register_node


class _FakeUser:
    id = 1


@pytest.mark.asyncio
async def test_node_library_includes_registered_plugin_nodes() -> None:
    @register_node
    class _LibraryPluginNode(Node):
        metadata = NodeMetadata(
            node_type="_test.library_plugin",
            category="custom",
            label="Library Plugin",
            description="Plugin node exposed through the node library",
        )

        async def execute(self, *args, **kwargs):
            return None

    try:
        response = await get_node_library(current_user=_FakeUser())
        node_types = {node.node_type for node in response.nodes}
        assert "_test.library_plugin" in node_types
    finally:
        node_registry.unregister("_test.library_plugin")


@pytest.mark.asyncio
async def test_node_library_includes_custom_algo_category_nodes() -> None:
    @register_node
    class _CustomAlgoCategoryNode(Node):
        metadata = NodeMetadata(
            node_type="_test.custom_algo_visible",
            category="custom_algo",
            label="Visible Custom Node",
            description="Legacy category nodes should still be visible if registered",
        )

        async def execute(self, *args, **kwargs):
            return None

    try:
        response = await get_node_library(current_user=_FakeUser())
        node_types = {node.node_type for node in response.nodes}
        assert "_test.custom_algo_visible" in node_types
    finally:
        node_registry.unregister("_test.custom_algo_visible")
