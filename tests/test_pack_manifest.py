"""Pack metadata stays inert and preserves exact reproducibility identities."""

import json

import pytest
from pydantic import ValidationError

from spectra_sherpa.core.pack_manifest import (
    PackManifest,
    PackManifestError,
    inspect_pack_availability,
    parse_pack_manifest,
    required_pack_references,
    validate_pack_set,
)


def pack(name="reference", **changes):
    values = dict(
        pack_id=name,
        version="1.0.0",
        build_sha256="a" * 64,
        core_min="0.6.4",
        core_max_exclusive="0.8.0",
        contract_versions=("4.0",),
        entitlement_id=f"pack.{name}",
        license_id="LicenseRef-Qualification-Fixture",
        nodes=(f"pro.{name}.record",),
        tools=(f"pro.{name}.inspect",),
    )
    values.update(changes)
    return PackManifest(**values)


def validate(*manifests):
    return validate_pack_set(manifests, core_version="0.7.0", contract_versions=frozenset({"4.0"}))


def test_manifest_is_inert_strict_and_frozen():
    manifest = pack()
    assert parse_pack_manifest(manifest.model_dump_json().encode()) == manifest
    with pytest.raises(ValidationError):
        manifest.version = "2.0.0"
    for field in ("module", "entrypoint", "renderer_code", "skill", "instructions"):
        payload = manifest.model_dump(mode="json")
        payload[field] = "untrusted"
        with pytest.raises(ValidationError):
            parse_pack_manifest(json.dumps(payload).encode())
    with pytest.raises(PackManifestError):
        parse_pack_manifest(b" " * 65537)
    duplicated = manifest.model_dump_json().replace('"version":"1.0.0"', '"version":"2.0.0","version":"1.0.0"')
    with pytest.raises(PackManifestError, match="Duplicate manifest field"):
        parse_pack_manifest(duplicated.encode())
    with pytest.raises(ValueError):
        parse_pack_manifest(b"[" * 2000 + b"]" * 2000)


@pytest.mark.parametrize(
    "changes",
    [
        {"pack_id": "../reference"},
        {"version": "latest"},
        {"build_sha256": "opaque"},
        {"nodes": ("model.pls",)},
        {"tools": ("pro.foreign.inspect",)},
        {"nodes": ("pro.reference.record", "pro.reference.record")},
        {"core_min": "0.8.0"},
        {"contract_versions": ("4.0", "4.0")},
    ],
)
def test_invalid_or_ambiguous_declarations_are_refused(changes):
    with pytest.raises(ValidationError):
        pack(**changes)


def test_dependency_order_is_deterministic_and_transitive():
    base = pack("base")
    left = pack("left", dependencies=(base.reference,))
    right = pack("right", dependencies=(base.reference,))
    top = pack("top", dependencies=(right.reference, left.reference))
    assert validate(top, right, base, left) == validate(left, base, right, top) == (base, left, right, top)


def test_cycles_and_duplicate_pack_identities_fail():
    first, second = pack("first"), pack("second")
    first = pack("first", dependencies=(second.reference,))
    second = pack("second", dependencies=(first.reference,))
    with pytest.raises(PackManifestError, match="cycle"):
        validate(first, second)
    with pytest.raises(PackManifestError, match="Duplicate"):
        validate(first, first)


@pytest.mark.parametrize("change", [{"version": "2.0.0"}, {"build_sha256": "b" * 64}])
def test_dependency_exact_version_and_build_are_both_required(change):
    base = pack("base")
    dependent = pack(dependencies=(base.reference,))
    with pytest.raises(PackManifestError, match="Missing or incompatible"):
        validate(dependent)
    with pytest.raises(PackManifestError, match="Missing or incompatible"):
        validate(dependent, pack("base", **change))


@pytest.mark.parametrize("core,contracts", [("0.6.3", {"4.0"}), ("0.8.0", {"4.0"}), ("0.7.0", {"3.0"})])
def test_core_and_contract_compatibility_fail_closed(core, contracts):
    with pytest.raises(PackManifestError, match="Incompatible"):
        validate_pack_set((pack(),), core_version=core, contract_versions=frozenset(contracts))


def test_unrelated_installed_packs_do_not_become_artifact_dependencies():
    base = pack("base")
    used = pack(dependencies=(base.reference,))
    unrelated = pack("unrelated")
    manifests = validate(unrelated, used, base)
    assert required_pack_references(("data.file_load", "model.fitted_pls"), manifests) == ()
    assert required_pack_references(("pro.reference.record", "data.file_load"), manifests) == (
        base.reference,
        used.reference,
    )
    with pytest.raises(PackManifestError, match="Unavailable pack node"):
        required_pack_references(("pro.missing.record",), manifests)


def test_equal_ports_do_not_hide_changed_build_identity():
    original = pack()
    changed = pack(build_sha256="b" * 64)
    assert changed.nodes == original.nodes and changed.tools == original.tools
    result = inspect_pack_availability((original.reference,), (changed.reference,))
    assert result[0].status == "different_build"
    assert result[0].required == original.reference and result[0].installed == changed.reference


def test_inspection_reports_missing_and_version_without_loading_code_or_claiming_permission():
    original = pack()
    assert inspect_pack_availability((original.reference,), ())[0].status == "missing"
    assert (
        inspect_pack_availability((original.reference,), (pack(version="2.0.0").reference,))[0].status
        == "different_version"
    )
    assert inspect_pack_availability((original.reference,), (original.reference,))[0].status == "matching_identity"
    with pytest.raises(PackManifestError, match="Duplicate"):
        inspect_pack_availability((original.reference,), (original.reference, original.reference))


def test_projection_independently_refuses_missing_dependencies_and_cycles():
    base, top = pack("base"), pack("top")
    top = pack("top", dependencies=(base.reference,))
    with pytest.raises(PackManifestError, match="Missing or incompatible"):
        required_pack_references(top.nodes, (top,))
    base = pack("base", dependencies=(top.reference,))
    with pytest.raises(PackManifestError, match="cycle"):
        required_pack_references(top.nodes, (top, base))
