"""Read exact retained diagnostic review evidence without current graph mutation authority."""

from asyncio import to_thread

from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.pca_review_evidence import SCHEMA
from spectra_sherpa.app.services.run_output_retention import read_output


async def retained_review_receipt(run, pca_id):
    if run is None:
        raise ValueError("Selection unavailable — rerun to enable sample selection.")
    try:
        evidence = RunEvidence.model_validate(run.evidence_completeness)
        item = evidence.outputs.get("__workflow__", {}).get("pca_review")
        if (
            item is None
            or item.state != "exact"
            or item.storage != "file"
            or not item.byte_count
            or item.byte_count > 16 * 1024 * 1024
        ):
            raise ValueError("Selection unavailable — rerun to enable sample selection.")
        data = (await to_thread(read_output, run.user_id, item)).get(pca_id, {})
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise ValueError("Exact review evidence unavailable; rerun to enable diagnostic interpretation.") from exc
    if data.get("schema_version") != SCHEMA:
        raise ValueError(data.get("unavailable_reason") or "Selection unavailable — rerun to enable sample selection.")
    if data.get("graph_digest") != run.integrity_hash:
        raise ValueError("Saved review evidence does not match the run graph.")
    return data


def verify_review_cohort(state, receipt):
    if state.get("cohort") and state["cohort"] != {
        key: receipt.get(key, []) for key in ("calibration_ids", "heldout_ids")
    }:
        raise ValueError("Train/test membership changed. Review cannot be transferred to a new partition.")
