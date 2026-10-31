"""Optional GUI labels for newly retained reviews; never observation keys."""

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


def review_display_labels(dataset: SherpaDataset, ids: list[str]) -> dict[str, str]:
    """Bind bounded labels to exact typed IDs, without guessing or truncating."""
    if sample_ids(dataset) != ids:
        raise ValueError("Display-label source differs from the exact review observation IDs.")
    axis = dataset.get_observation_axis()
    if not isinstance(axis, SampleAxis) or axis.labels is None:
        return {}
    labels = axis.labels
    if len(labels) != len(ids):
        raise ValueError("Display labels are not aligned with the review observation IDs.")
    return {
        identity: label
        for identity, label in zip(ids, labels, strict=True)
        if isinstance(label, str) and label.strip() and len(label.encode("utf-8")) <= 512
    }
