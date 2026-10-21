"""Original synthetic intensities; reproduce provider axis declarations only."""

import hashlib
import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.jcamp_reader import NIST_QUANT_IR_AXIS_POLICY, parse_jcamp
from spectra_sherpa.io import UnreadableSpectrumError, UnsupportedFormatVariantError, ingest


def nist_style_text():
    count = 3526
    axis = np.linspace(575.653, 3974.61, count)
    values = np.arange(count) % 17 - 8
    lines = [
        "##TITLE=Original synthetic axis-regression fixture",
        "##DATA TYPE=INFRARED SPECTRUM",
        "##XUNITS=cm-1",
        "##YUNITS=(micromol/mol)-1m-1 (base 10)",
        "##FIRSTX=575.653",
        "##LASTX=3974.61",
        "##NPOINTS=3526",
        "##DELTAX=0.9645",
        "##XFACTOR=1.0",
        "##YFACTOR=0.01",
        "##XYDATA=(X++(Y..Y))",
    ]
    for start in range(0, count, 6):
        checkpoint = axis[max(0, start - 1)]
        lines.append(f"{checkpoint:.2f} " + " ".join(str(v) for v in values[start : start + 6]))
    return "\n".join([*lines, "##END="]), axis, values * 0.01


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
async def test_provider_reconciliation_survives_cache_synthesis_and_npz(monkeypatch, tmp_path):
    from spectra_sherpa.app.lib.synthetic_npz import load_synthetic_npz
    from spectra_sherpa.app.schemas.synthesis import SynthesisRequest
    from spectra_sherpa.app.services import synthesis as service

    text, axis, values = nist_style_text()
    downloads = []

    async def download(cas, *, index, destination):
        downloads.append((cas, index))
        destination.write_text(text, encoding="utf-8")

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
    assert provenance["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
