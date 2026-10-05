"""Security boundary: local OSS never discovers or runs third-party Python."""

from __future__ import annotations

import importlib
import importlib.util

import pytest

from spectra_sherpa.app.services.dag.node_base import Node, node_registry


def test_plugin_and_custom_package_execution_modules_do_not_ship() -> None:
    sdk = importlib.import_module("spectra_sherpa.sdk")
    modules = (
        "spectra_sherpa.app.services.plugin_loader",
        "custom_package_execution",
        "custom_package_install",
        "custom_package_lock",
        "custom_package_manifest",
        "custom_package_trust",
        "custom_package_worker",
    )
    for name in modules[1:]:
        assert name not in sdk.__all__
        assert name not in dir(sdk)
    qualified = (modules[0], *(f"spectra_sherpa.sdk.{name}" for name in modules[1:]))
    for name in qualified:
        assert importlib.util.find_spec(name) is None


def test_installed_canonical_registry_cannot_be_expanded_at_runtime() -> None:
    inspected = False

    class HostileNode(Node):
        @classmethod
        def get_metadata(cls):
            nonlocal inspected
            inspected = True
            raise AssertionError("frozen registry inspected an untrusted candidate")

    with pytest.raises(ValueError, match="runtime node registration is disabled"):
        node_registry.register(HostileNode)

    assert inspected is False
