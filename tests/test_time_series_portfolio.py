import pytest
from pydantic import ValidationError

from spectra_sherpa.core.time_series_portfolio import (
    AcquisitionInterval,
    AveragingParameters,
    StepPartition,
    TimeSeriesPortfolio,
    acquisition_batches,
)


def partition(**changes):
    data = dict(
        experiment_id=1,
        file_id=2,
        process_file_id=3,
        source_sha256="a" * 64,
        process_sha256="b" * 64,
        oes_dictionary_sha256="c" * 64,
        process_dictionary_sha256="d" * 64,
        segmentation_sha256="e" * 64,
        day="2024-08-05",
        wafer="01",
        asset_id="Wafer_01",
        step_id="production",
        recipe="BOSCH",
        intervals=(
            AcquisitionInterval(first=1, last=4, phase="etch", cycle=1),
            AcquisitionInterval(first=7, last=9, phase="etch", cycle=2),
        ),
    )
    return StepPartition(**(data | changes))


def test_three_modes_preserve_independent_wafers():
    a = partition()
    b = partition(wafer="02", asset_id="Wafer_02")
    for mode, groups in [("step", 1), ("phase_across_cycles", 1), ("cycle_phase", 2)]:
        params = AveragingParameters(mode=mode)
        assert params.transition_trim_seconds == 0
        keys = {params.group_key(a, i) for i in a.intervals}
        assert len(keys) == groups
        assert keys.isdisjoint({params.group_key(b, i) for i in b.intervals})


def test_bounded_batches_preserve_gaps_and_original_acquisition_numbers():
    slices = [s for _, s in acquisition_batches(partition(), batch_rows=2)]
    assert [(s.start, s.stop) for s in slices] == [(0, 2), (2, 4), (6, 8), (8, 9)]
    with pytest.raises(ValueError):
        list(acquisition_batches(partition(), batch_rows=0))


def test_immutable_receipt_binds_both_dictionaries_and_selection():
    a = TimeSeriesPortfolio(project_id=1, partitions=(partition(),))
    assert a == TimeSeriesPortfolio.model_validate_json(a.model_dump_json())
    for key in ["oes_dictionary_sha256", "process_dictionary_sha256", "segmentation_sha256"]:
        b = TimeSeriesPortfolio(project_id=1, partitions=(partition(**{key: "f" * 64}),))
        assert a.sha256() != b.sha256()
    with pytest.raises(ValidationError):
        a.project_id = 2
    with pytest.raises(ValidationError):
        TimeSeriesPortfolio(project_id=1, partitions=(partition(), partition()))
    with pytest.raises(ValidationError):
        TimeSeriesPortfolio(project_id=1, partitions=())


def test_no_invented_cycles_or_hidden_weights():
    interval = AcquisitionInterval(first=1, last=2, phase="clean")
    assert AveragingParameters(mode="cycle_phase").group_key(partition(), interval)[-2:] == (None, "clean")
    with pytest.raises(ValidationError):
        AveragingParameters(mode="step", weighting="equal_wafer")
    with pytest.raises(ValidationError):
        AveragingParameters(mode="step", transition_trim_seconds=float("nan"))
    with pytest.raises(ValidationError):
        partition(
            intervals=(
                AcquisitionInterval(first=2, last=3, phase="etch"),
                AcquisitionInterval(first=3, last=4, phase="passivation"),
            )
        )
