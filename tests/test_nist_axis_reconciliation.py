"""Original synthetic intensities; reproduce provider axis declarations only."""

import hashlib
import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.jcamp_reader import LEGACY_NIST_QUANT_IR_AXIS_POLICY, NIST_QUANT_IR_AXIS_POLICY, parse_jcamp
from spectra_sherpa.io import UnreadableSpectrumError, UnsupportedFormatVariantError, ingest


def nist_style_text(first="575.653", last="3974.61", count=3526, delta="0.9645", offset=1):
    axis = np.linspace(float(first), float(last), count)
    values = np.arange(count) % 17 - 8
    lines = [
        "##TITLE=Original synthetic axis-regression fixture",
        "##DATA TYPE=INFRARED SPECTRUM",
        "##XUNITS=cm-1",
        "##YUNITS=(micromol/mol)-1m-1 (base 10)",
        f"##FIRSTX={first}",
        f"##LASTX={last}",
        f"##NPOINTS={count}",
        f"##DELTAX={delta}",
        "##XFACTOR=1.0",
        "##YFACTOR=0.01",
        "##XYDATA=(X++(Y..Y))",
    ]
    for start in range(0, count, 6):
        checkpoint = axis[max(0, start - offset)]
        lines.append(f"{checkpoint:.2f} " + " ".join(str(v) for v in values[start : start + 6]))
    return "\n".join([*lines, "##END="]), axis, values * 0.01


@pytest.mark.parametrize(
    "first,last,count,delta",
    [
        ("575.169", "3975.077", 7053, "0.4820"),  # Acetone, 1 cm^-1 B-H
        ("574.928", "3975.077", 14106, "0.2410"),  # Acetone, 0.5 cm^-1 B-H
        ("575.171", "3974.61", 7052, "0.4820"),  # Benzene, 1 cm^-1 B-H
        ("574.687", "3974.595", 3527, "0.9645"),  # Acetone, 2 cm^-1 Boxcar
        ("575.653", "3974.61", 3526, "0.9645"),  # Benzene, 2 cm^-1 Boxcar
    ],
)
@pytest.mark.parametrize("offset", [0, 1])
def test_precision_policy_preserves_exact_endpoint_axis_and_values(first, last, count, delta, offset):
    text, axis, values = nist_style_text(first, last, count, delta, offset)
    parsed = parse_jcamp(text, axis_policy=NIST_QUANT_IR_AXIS_POLICY)
    np.testing.assert_array_equal(parsed.x, axis)
    np.testing.assert_array_equal(parsed.y, values)
    assert parsed.axis_reconciliation["checkpoint_offset_samples"] == offset
    assert parsed.axis_reconciliation["policy"] == "nist-quant-ir-fixed-grid-v2"
    # Provenance states the bound actually enforced on the declared step.
    decision = parsed.axis_reconciliation
    assert decision["declared_step_endpoint_drift"] <= decision["maximum_allowed_declared_step_endpoint_drift"]
    assert decision["declared_step_relative_deviation"] <= decision["maximum_allowed_step_relative_deviation"]
    assert decision["max_checkpoint_error"] <= decision["maximum_allowed_checkpoint_error"]
    with pytest.raises(ValueError):
        parse_jcamp(text)  # Neither provider labels nor compatible checkpoints opt ordinary imports in.


@pytest.mark.parametrize("delta", ["0.4830", "0.4826"])
@pytest.mark.parametrize("offset", [0, 1])
def test_precision_policy_bounds_declared_step_drift(delta, offset):
    """Checkpoint spacing alone admitted 0.483 cm^-1, about 13 intervals of drift."""
    text, _, _ = nist_style_text("575.169", "3975.077", 7053, delta, offset)
    with pytest.raises(ValueError, match="DELTAX deviates"):
        parse_jcamp(text, axis_policy=NIST_QUANT_IR_AXIS_POLICY)


def test_previous_policy_remains_replayable_and_refuses_acetone_drift():
    text, _, _ = nist_style_text()
    old = parse_jcamp(text, axis_policy=LEGACY_NIST_QUANT_IR_AXIS_POLICY)
    assert old.axis_reconciliation["policy"] == "nist-quant-ir-fixed-grid-v1"
    assert "checkpoint_offset_samples" not in old.axis_reconciliation
    acetone, _, _ = nist_style_text("575.169", "3975.077", 7053, "0.4820")
    with pytest.raises(ValueError, match="one-interval"):
        parse_jcamp(acetone, axis_policy=LEGACY_NIST_QUANT_IR_AXIS_POLICY)


def test_correctly_rounded_step_is_validated_against_endpoints():
    text, axis, values = nist_style_text("100.000", "116.949", 18, "1.00", 0)
    parsed = parse_jcamp(text, axis_policy=NIST_QUANT_IR_AXIS_POLICY)
    np.testing.assert_array_equal(parsed.x, axis)
    np.testing.assert_array_equal(parsed.y, values)


def test_ambiguous_checkpoint_offset_is_refused():
    text = (
        "##TITLE=Original ambiguous fixture\n##XUNITS=cm-1\n##FIRSTX=100.0\n"
        "##LASTX=100.4\n##NPOINTS=3\n##DELTAX=0.2\n##XYDATA=(X++(Y..Y))\n"
        "100.0 1\n100.1 2\n100.3 3\n##END=\n"
    )
    with pytest.raises(ValueError, match="ambiguous"):
        parse_jcamp(text, axis_policy=NIST_QUANT_IR_AXIS_POLICY)


@pytest.mark.parametrize("corruption", ["two-samples", "mixed-offset", "coarse-checkpoint", "coarse-delta", "too-few"])
def test_precision_policy_does_not_hide_contradictory_or_unverifiable_checkpoints(corruption):
    text, _, _ = nist_style_text("575.169", "3975.077", 7053, "0.4820", 2 if corruption == "two-samples" else 1)
    if corruption == "mixed-offset":
        # Second checkpoint becomes unshifted; subsequent ones keep the lag.
        text = text.replace("577.58 ", "578.06 ")
    elif corruption == "coarse-checkpoint":
        text = text.replace("577.58 ", "578 ")
    elif corruption == "coarse-delta":
        text = text.replace("##DELTAX=0.4820", "##DELTAX=0.5")
    elif corruption == "too-few":
        text = _strict_jcamp(0)
    with pytest.raises(ValueError):
        parse_jcamp(text, axis_policy=NIST_QUANT_IR_AXIS_POLICY)


def test_strict_default_refuses_but_explicit_nist_policy_retains_axis_decision(tmp_path):
    text, axis, values = nist_style_text()
    path = tmp_path / "provider.jdx"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(UnreadableSpectrumError, match="DELTAX contradicts"):
        ingest(path)
    result = ingest(path, parser_options={"axis_policy": NIST_QUANT_IR_AXIS_POLICY})
    dataset = result.assets[0].dataset
    np.testing.assert_array_equal(dataset.feature_axis.values, axis)
    np.testing.assert_array_equal(dataset.X[0], values)
    decision = dataset.extra["jcamp.axis_reconciliation"]
    assert decision["axis_authority"] == "FIRSTX/LASTX/NPOINTS"
    assert decision["original_declarations"]["DELTAX"] == "0.9645"
    assert decision["max_checkpoint_error"] > 0.96
    assert decision["max_checkpoint_error"] <= decision["maximum_allowed_error"]
    assert decision["values_reordered_or_interpolated"] is False
    assert result.source_members[0].sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.warnings and "reconciled" in result.warnings[0]
    with pytest.raises(UnsupportedFormatVariantError):
        ingest(path, parser_options={"axis_policy": "ignore-errors"})
    legacy = ingest(path, parser_options={"axis_policy": LEGACY_NIST_QUANT_IR_AXIS_POLICY})
    assert legacy.assets[0].dataset.extra["jcamp.axis_reconciliation"]["policy"] == LEGACY_NIST_QUANT_IR_AXIS_POLICY


def test_provider_refusal_gives_provider_remedy_not_local_file_advice(tmp_path):
    text, _, _ = nist_style_text()
    path = tmp_path / "refused.jdx"
    path.write_text(text.replace("##DELTAX=0.9645", "##DELTAX=-0.9645"))
    with pytest.raises(UnreadableSpectrumError) as caught:
        ingest(path, parser_options={"axis_policy": NIST_QUANT_IR_AXIS_POLICY})
    assert "NIST resolution/apodization" in str(caught.value)
    assert "Export the source again" not in str(caught.value)


@pytest.mark.parametrize(
    "old,new",
    [
        ("##DELTAX=0.9645", "##DELTAX=0.97"),
        ("##DELTAX=0.9645", "##DELTAX=-0.9645"),
        ("##DELTAX=0.9645", "##DELTAX=nan"),
        ("##LASTX=3974.61", "##LASTX=nan"),
        ("##NPOINTS=3526", "##NPOINTS=3525"),
        ("##FIRSTX=575.653", "##FIRSTX=580.0"),
        ("##XFACTOR=1.0", "##XFACTOR=0"),
        ("##YFACTOR=0.01", "##YFACTOR=garbage"),
        ("##XUNITS=cm-1", "##XUNITS=nm"),
        ("580.47 ", "578.00 "),
    ],
)
def test_explicit_nist_policy_still_refuses_malformed_or_larger_contradictions(old, new):
    text, _, _ = nist_style_text()
    assert old in text
    with pytest.raises(ValueError):
        parse_jcamp(text.replace(old, new), axis_policy=NIST_QUANT_IR_AXIS_POLICY)


@pytest.mark.asyncio
@pytest.mark.parametrize("line_ending", ["\n", "\r\n"], ids=["LF", "CRLF"])
async def test_provider_reconciliation_survives_cache_synthesis_and_npz(monkeypatch, tmp_path, line_ending):
    from spectra_sherpa.app.lib.synthetic_npz import load_synthetic_npz
    from spectra_sherpa.app.schemas.synthesis import SynthesisRequest
    from spectra_sherpa.app.services import synthesis as service

    text, axis, values = nist_style_text()
    source_bytes = text.replace("\n", line_ending).encode("utf-8")
    downloads = []

    async def download(cas, *, index, destination):
        downloads.append((cas, index))
        # Downloads retain exact provider bytes, without OS text translation.
        destination.write_bytes(source_bytes)

    monkeypatch.setattr(service, "_synthesis_cache_dir", lambda _source: tmp_path)
    monkeypatch.setattr(service, "_download_nist_quant_ir_jcamp", download)
    options = dict(resolution_cm1=2.0, apodization="Boxcar", wavenumber_min=None, wavenumber_max=None)
    first = await service._get_nist_component_spectrum("nist_quant_ir:benzene", **options)
    second = await service._get_nist_component_spectrum("nist_quant_ir:benzene", **options)
    assert len(downloads) == 1 and not first.cached and second.cached
    assert first.metadata == second.metadata
    np.testing.assert_array_equal(first.wavenumber, axis)
    np.testing.assert_array_equal(first.intensity, values)
    request = SynthesisRequest(
        settings={"source": "nist_quant_ir", "n_samples": 2, "noise_sigma_au": 0, "seed": 42},
        components=[
            {
                "component_id": first.component_id,
                "spectrum": first.model_dump(),
                "control_points": [{"x": 0, "y_ppm": 1}, {"x": 1, "y_ppm": 2}],
            }
        ],
    )
    result = service.synthesize(request)
    path = tmp_path / "retained.npz"
    service._write_synthesis_npz(path, result)
    retained = load_synthetic_npz(path)
    provenance = json.loads(retained["recipe_json"])["components"][0]["source_provenance"]
    assert provenance == first.metadata
    assert provenance["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()


def _strict_jcamp(shift: int) -> str:
    values = " ".join(str(10 + shift + index) for index in range(5))
    return (
        f"##TITLE=s{shift}\n##JCAMP-DX=4.24\n##DATA TYPE=INFRARED SPECTRUM\n##XUNITS=1/CM\n"
        "##YUNITS=ABSORBANCE\n##FIRSTX=1000\n##LASTX=1004\n##NPOINTS=5\n##DELTAX=1\n"
        f"##XFACTOR=1\n##YFACTOR=1\n##XYDATA=(X++(Y..Y))\n1000 {values}\n##END=\n"
    )


@pytest.mark.parametrize(
    "line_ending,expected_digest",
    [
        ("\n", "b8342a44ed01f1719614ef3f13feafb2f461a7319e63c11f4f6c9691b26a2f79"),
        ("\r\n", "335822ad1694e74773fa85f5a3815b29f7c0310c549d14939715c7618f16b3c4"),
    ],
    ids=["LF", "CRLF"],
)
def test_strict_jcamp_collection_identity_is_unchanged_by_the_nist_policy(tmp_path, line_ending, expected_digest):
    """Saved multi-file JCAMP bindings pin this digest; parser identity is part of it."""
    from spectra_sherpa.app.lib.collection_assembly import CollectionMember, assemble_collection

    members = []
    for index in range(2):
        path = tmp_path / f"s{index}.jdx"
        path.write_bytes(_strict_jcamp(index).replace("\n", line_ending).encode("utf-8"))
        source = path.read_bytes()
        result = ingest(path)
        assert result.parser_version == "2"
        assert "jcamp.axis_reconciliation" not in result.assets[0].dataset.extra
        members.append(
            CollectionMember(result.assets[0].dataset, path.name, len(source), hashlib.sha256(source).hexdigest())
        )
    collection = assemble_collection(members, title="c")
    # Original LF digest (main 2db5db96), plus the same source with CRLF.
    # Collection custody intentionally binds exact source bytes, not normalized text.
    assert collection.scientific_digest == expected_digest
