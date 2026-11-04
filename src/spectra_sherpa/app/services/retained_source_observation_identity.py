"""Read-only identity recovery from a split branch's retained row-custody receipt.

Some admitted sources declare display labels but no typed ``sample_id`` column.
Collection assembly still retains a receipt binding each ordered row to its
source file hash. That receipt, not the labels, qualifies a split branch here,
and only when it exactly reproduces the branch's retained split rows.
"""

from __future__ import annotations

from spectra_sherpa.app.lib.collection_assembly import verified_source_observations


def source_observation_ids(branch_payload: object, split: str, branch: str, plan: dict) -> list[str] | None:
    """Return exact branch IDs, or None when the receipt cannot qualify them."""
    from spectra_sherpa.app.services.paired_evaluation import restore_dataset

    if branch not in {"train", "test"} or not isinstance(branch_payload, dict):
        return None
    try:
        dataset = restore_dataset(branch_payload)
        verified = [row["sample_id"] for row in verified_source_observations(dataset)]
        source_rows = dataset.meta["source_observations"]
        indices = plan["train_indices" if branch == "train" else "test_indices"]
        # The receipt describes the split input. A filtered or reordered input
        # has no exact row mapping here, so it stays unqualified.
        if len(source_rows) != plan["n_samples"] or verified != [source_rows[i]["sample_id"] for i in indices]:
            return None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
    receipts = [
        entry
        for entry in branch_payload.get("provenance", [])
        if entry.get("op_id") == "data.train_test_split" and entry.get("node_id") == split
    ]
    if not receipts:
        return None
    parameters = receipts[-1].get("parameters", {})
    if parameters.get("digest") != plan["digest"] or parameters.get("split") != branch:
        return None
    return verified
