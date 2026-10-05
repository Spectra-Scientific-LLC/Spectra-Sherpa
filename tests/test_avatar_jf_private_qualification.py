"""Optional exact-corpus gate for the private JF same-source triplets."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_exact_private_avatar_jf_triplets_reproduce_native_parser_receipt() -> None:
    private_root = os.environ.get("SPECTRASHERPA_AVATAR_JF_PRIVATE_INPUTS")
    if not private_root:
        pytest.skip("private Avatar JF triplet corpus is not installed")
    tool = Path(__file__).resolve().parents[1] / "tools" / "qualify_avatar_jf_parser_triplets.py"
    completed = subprocess.run(
        [sys.executable, str(tool), "--input-dir", private_root],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "pass"
    assert receipt["summary"] == {
        "minimum_absorbance_correlation": 0.9999999999999797,
        "sample_count": 6,
        "spa_csv_absorbance_max_abs_difference": pytest.approx(4.9908828736455746e-8),
        "spa_csv_axis_max_abs_difference_cm-1": pytest.approx(0.0007232925586322381),
        "spa_jdx_absorbance_max_abs_difference": pytest.approx(7.999977125194846e-9),
        "spa_jdx_axis_max_abs_difference_cm-1": pytest.approx(3.7500012695090845e-7),
        "spectrochempy_loaded": False,
    }


def test_exact_private_avatar_apex_stress_corpus_reproduces_native_parser_receipt() -> None:
    private_root = os.environ.get("SPECTRASHERPA_AVATAR_JF_PRIVATE_INPUTS")
    if not private_root:
        pytest.skip("private Avatar Apex stress corpus is not installed")
    tool = Path(__file__).resolve().parents[1] / "tools" / "qualify_avatar_apex_parser_stress.py"
    completed = subprocess.run(
        [sys.executable, str(tool), "--input-dir", private_root],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "pass"
    assert receipt["summary"] == {
        "archive_count": 5,
        "instrument_resaved_spa_count": 2,
        "literal_dot_spa_filename_parsed": True,
        "parsed_member_count": 50,
        "spectrochempy_loaded": False,
        "typical_spa_count": 34,
        "typical_spa_quantity_census": {
            "Absorbance": 20,
            "Log reflectance": 1,
            "Photoacoustic intensity": 1,
            "Raman intensity": 1,
            "Reflectance": 1,
            "Transmittance": 10,
        },
        "typical_spa_sources_with_preserved_missing_values": 2,
    }
    assert receipt["counterparts"]["lubed"]["spa_csv_missing_value_count"] == 66
    assert receipt["counterparts"]["unlubed"]["spa_csv_missing_value_count"] == 66
    assert receipt["counterparts"]["lubed"]["preprocessing_policy"] == {
        "uncropped_snv": "refused_missing_input",
        "remediation": "preprocess.clip_range_900_to_4005_cm-1",
        "clipped_feature_count": 805,
        "clipped_snv": "finite",
    }
    assert (
        receipt["counterparts"]["unlubed"]["preprocessing_policy"]
        == receipt["counterparts"]["lubed"]["preprocessing_policy"]
    )
    assert receipt["instrument_observation"]["lubed_unlubed"] == {
        "displayed_range_cm-1": [900.0, 4000.0],
        "displayed_y_quantity": "Transmittance",
        "nothing_displayed_below_cm-1": 900.0,
        "number_of_points": 871,
        "processing_history_blank": {"from_cm-1": 900.4581, "to_cm-1": 398.6646},
        "processing_history_final_format": "Single Beam",
        "x_axis": "Wavenumbers (cm-1)",
    }
    reference = receipt["counterparts"]["acetominophen_caffeine_acetylsalicylic_acid"]
    assert reference["jdx_comparison_scale_only"] == 100.0
    assert reference["spa_spc_signal_max_abs_difference"] == 0.0
