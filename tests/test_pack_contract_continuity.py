"""Retained pack compatibility never authorizes historical execution."""

import json
from copy import deepcopy
from importlib.resources import files
from types import SimpleNamespace

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.historical_contracts import HistoricalReconstructionContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, assert_admitted_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.contract_compatibility import (
    _PACK_RETENTION_APPLICATION_PREDECESSORS,
    inspection_predecessor_catalog,
    pack_retention_inspection_registration,
    saved_state_predecessor_is_compatible,
)
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract

PROFILE = "a66a3b73b19b1e864df07a5e1622b8f8c9fa75b65a36b83ee2b7c3b84da680cf"
CHANGED = {
    "baseline.rubberband": "e95b6d6912f9e120ced468d610b5bd9adc7a41ee105e54e6ef1aefcc40864ed2",
    "classification.knn": "afa3c39e6b993820de1d95d74275e38cedc5fcec25f3eac319ceb963124443a3",
    "classification.plsda": "8409cc148280932c5dfbde40f68477b834aceb92f268acc682b23162b9d6a9e2",
    "classification.simca": "ab489af8b627c076387254ee39e9a6c1d5657522712452b0f60ada486eccf6dd",
    "custom.golden_grid_align": "4fc4c2f1713aff5225fa543686ca122907fc74fff0e7a30af08aaad0b9676913",
    "custom.hybrid_selector": "71029bebe889a50c865a85c9594fac68ba08059eaf876873d1a0c07a9cedcf91",
    "custom.linear_calibration": "2548b9fa106d27864482d0b4042b70e4e4dbf5f22ed452c4ef914742f0ae4332",
    "custom.noise_injection": "72933054d9e3f7990d6cbf2654aea7dc202ba165b138ee13b62db14a85d7b3d8",
    "custom.saturation_model": "b8b82f83727ca8ea6f7d5adbfa2156501edac4995a96395f3db76dde8eddcc18",
    "custom.system_saturation": "881e7c203dd4f056d30269f1d06f19d42a2da6214350dcd1562da4a7cd8ac4fa",
    "data.collection_load": "4e0a615ce581879bc1f8f5e21e0024a1ab9bf665ece18505fde6bc346cf79602",
    "data.file_load": "1e5ede067a30af3bf377a416a3f88973e553d1f82937f01215c26e7838528f6d",
    "data.load_group": "f540eceba671bad1af3a4ec1c7fb8e1060e97bfe1bdd2bc78ecf54151d4beba4",
    "data.nist_library": "528651c6627f2082f580cee4349bc63d73d9e31bfde13ac2d0f7ad23c2be7373",
    "data.synthetic_curve": "964ed0896e6a81b185e514876abef565d5e2d5906d8fda0344f3e161f61985b4",
    "diagnostics.labeled_regression_evaluator": "779a67294b03730c740771ab3c6911899430ba69d5c6b1befdaa719968334924",
    "model.apply_fitted_linear_regression": "68c62ab73f3c5becfe36744a7ff5a538c5d0a82c6dcd9ce4a805cb498c5f3f56",
    "model.apply_fitted_pcr": "dee5dd3ffcf96da7cf0c380017142de516490732c9c44e666a32b4cbfed7918f",
    "model.apply_fitted_svr": "ad9502a76af85fff45d28e0377350c56e0fb694edddb4d6feceaabf3144f837d",
    "model.fitted_linear_regression": "a4a5fd5ff397ef611f71068c585590acb82c59d9a2d4a13c68d332d49594f717",
    "model.fitted_pcr": "512f25478a1fd7e5623b26e9aeba7d248a15d4edbd20d776e8ba7d1de7efe545",
    "model.fitted_svr": "6cd8e43f86977cbaa50bb9004ae2cb2ba795e7c95f4159071e263acdcf895c55",
    "model.ica": "3f1a10bafee2b5c991be7b034ff1e04ad76d499af9c915070090284b05d3504a",
    "model.linear_regression": "df73eaef62cac50a176c35c59058cbc31b5caf46ccaf714b21f910307b483c12",
    "model.load_apply": "71ce63198859477d3485008be6c228d82f51f5406846893869ce4af32fc96989",
    "model.mcr_als": "94cc691ab58ed8ceff82b57938ef025609a73e8f90aad89f5e0d59b810462939",
    "model.pca": "ff32cbbbd0802510c30246d8c8561bb6e83e23143a9dd7d6311061ea3a8ce786",
    "model.pcr": "e976b5bfbcc478a019a8954c536a45c000546d4fd7e3bdec72a3c77435b7f574",
    "model.svr": "342c43cb286578882662e66c84d105cd95e90ba2f7fa051e08c93ea0be4e74fb",
    "preprocess.clip_floor": "0923a1774db6f5854c54841742684f3f69cb346c6ca30f8eebbdfc143453417d",
    "preprocess.clip_range": "07f9b5b8ee9a0b3992138e6dc86986cfbb7a6b91ed0f8653b5f174f563e8bd38",
    "preprocess.cosmic_ray": "0d06637cca6092a38af01ae56247cd210312d5419aecf18856a24082cd6010a9",
    "preprocess.wavenumber_align": "d398d1996248635dc5453103168c102bf1ccdc4b7aec75c6417089f5f32a0239",
    "synthesis.blend": "faaabc3a15a20b19d1f75fbc37db11c6356c240c70211b24f4f70c81e4b1383f",
    "synthesis.hitran_response": "fe133fb0150603badb199dfde8b8ad010e7682dd1caeab45fc8b2cc8999a1cee",
    "synthesis.merge": "eb3e0a596a880f563c79bb558f1ec7c7a0a51ef513da651be4c401219649a424",
    "synthesis.nist_quant_ir_response": "25d2f9668b94d6a437c915d2b9459f2114554b3c4811ff4cebac371b8fac7751",
    "synthesis.ppm_fraction": "b0b7bf7bc4a90871871ef63dc257248243d9c810876d08eb575d02f54bcb75de",
    "synthesis.species": "82791da8613576d1159ff12421787e95f34b4142e127096f49c44c94d2e214a3",
}


@pytest.fixture(autouse=True)
def types():
    if not type_registry.is_loaded:
        type_registry.load(files("spectra_sherpa.app").joinpath("types"))


def test_exact_contract_changes_preserve_all_scientific_declarations():
    before = inspection_predecessor_catalog(PROFILE)
    live = {m.node_type: c for m in node_registry.list_nodes() if (c := m.resolved_execution_contract()) is not None}
    assert set(live) == set(before["contracts"])
    assert {op: c.digest for op, c in live.items() if c.digest != before["contracts"][op]["digest"]} == CHANGED
    for op, old in before["contracts"].items():
        assert NodeExecutionContract.from_dict(old["payload"]).digest == old["digest"]
        ignored = {"implementation_components", "implementation_digest"}
        assert {k: v for k, v in old["payload"].items() if k not in ignored} == {
            k: v for k, v in live[op].as_dict().items() if k not in ignored
        }


@pytest.mark.parametrize("entry", _PACK_RETENTION_APPLICATION_PREDECESSORS)
def test_direct_readers_are_closed_and_directional(entry):
    assert node_registry.get_metadata(entry.operation_id).resolved_execution_contract().digest == entry.consumer_digest
    args = dict(operation_id=entry.operation_id, serializer=entry.serializer)
    assert saved_state_predecessor_is_compatible(entry.predecessor_digest, entry.consumer_digest, **args)
    assert not saved_state_predecessor_is_compatible(entry.consumer_digest, entry.predecessor_digest, **args)
    assert not saved_state_predecessor_is_compatible("f" * 64, entry.consumer_digest, **args)
    assert not saved_state_predecessor_is_compatible(
        entry.predecessor_digest, entry.consumer_digest, operation_id="unknown", serializer=entry.serializer
    )
    assert not saved_state_predecessor_is_compatible(
        entry.predecessor_digest, entry.consumer_digest, operation_id=entry.operation_id, serializer="unknown"
    )


REGISTRATIONS = json.loads(files("spectra_sherpa.core").joinpath("contract_inspection_pack_retention.json").read_text())


@pytest.mark.parametrize("entry", REGISTRATIONS)
def test_each_historical_registration_preserves_original_identity(entry):
    profile, op, predecessor, consumer = (
        entry[k] for k in ("profile_digest", "operation_id", "predecessor_digest", "consumer_digest")
    )
    assert node_registry.get_metadata(op).resolved_execution_contract().digest == consumer
    assert HistoricalReconstructionContext(profile).contract(op, predecessor).digest == predecessor
    assert pack_retention_inspection_registration(profile, op, predecessor, consumer) == entry
    for fields in (
        ("f" * 64, op, predecessor, consumer),
        (profile, "unknown", predecessor, consumer),
        (profile, op, "f" * 64, consumer),
        (profile, op, predecessor, "f" * 64),
    ):
        assert pack_retention_inspection_registration(*fields) is None


def test_prepack_profile_and_graph_remain_inert():
    context = HistoricalReconstructionContext(PROFILE)
    assert context.profile().digest == PROFILE
    graph = context.reconstruct([WorkflowNode("classifier", "classification.plsda", {"n_components": 2})], [])
    assert context.graph(graph.as_dict()).as_dict() == graph.as_dict()
    with pytest.raises(ValidationGraphError):
        assert_admitted_validation_graph(graph)
    with pytest.raises(ValueError):
        HistoricalReconstructionContext("f" * 64)


@pytest.mark.parametrize("profile", [PROFILE, "d82af6a5a5b9922b1c57531d3ce9d121ad6e7c6f80ee3dc6bb24119f6b2f24c9"])
@pytest.mark.parametrize(
    "field",
    [
        "semantic_outputs",
        "parameter_schema_digest",
        "fitted_state_serializer",
        "runtime_requirements",
        "implementation_version",
    ],
)
def test_changed_declarations_never_inherit_exact_reader(profile, field, monkeypatch):
    context = HistoricalReconstructionContext(profile)
    op = "classification.plsda"
    predecessor = context._catalog["profile"]["operations"][op]
    metadata = node_registry.get_metadata(op)
    current = metadata.resolved_execution_contract()
    payload = dict(current.payload)
    payload[field] = () if field in {"semantic_outputs", "runtime_requirements"} else "altered"
    monkeypatch.setattr(
        metadata, "resolved_execution_contract", lambda: SimpleNamespace(digest=current.digest, payload=payload)
    )
    with pytest.raises(ValidationGraphError, match="scientific declarations changed"):
        context.contract(op, predecessor)


def test_corrupt_existing_payload_is_not_replaced_by_frozen_fallback():
    context = HistoricalReconstructionContext(PROFILE)
    op = "classification.plsda"
    predecessor = context._catalog["profile"]["operations"][op]
    context._catalog = deepcopy(context._catalog)
    context._catalog["contracts"][op]["payload"]["implementation_version"] = "corrupted"
    with pytest.raises(ValidationGraphError, match="unknown historical operation/contract identity"):
        context.contract(op, predecessor)
