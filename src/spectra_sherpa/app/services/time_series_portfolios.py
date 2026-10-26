"""Application admission and immutable receipt construction for OES portfolios."""

import asyncio
import hashlib
from importlib.resources import files
from pathlib import Path

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select

from spectra_sherpa.app.api.v1.routes.experiments import _bosch_comparison_paths, _require_experiment
from spectra_sherpa.app.models.time_series_portfolio import TimeSeriesPortfolioRecord
from spectra_sherpa.app.services.dag.nodes import bosch_phases
from spectra_sherpa.core.time_series_portfolio import AcquisitionInterval, StepPartition, TimeSeriesPortfolio
from spectra_sherpa.io.bosch_netcdf import bosch_phase_observations
from spectra_sherpa.io.registry import builtin_registry


def dictionary_hash(name):
    return hashlib.sha256(files("spectra_sherpa").joinpath("data", "bosch_netcdf", name).read_bytes()).hexdigest()


async def admit_portfolio(session, user_id, project_id, portfolio_id, digest):
    record = await session.scalar(
        select(TimeSeriesPortfolioRecord).where(
            TimeSeriesPortfolioRecord.id == portfolio_id, TimeSeriesPortfolioRecord.project_id == project_id
        )
    )
    if record is None:
        raise HTTPException(404, "Portfolio not found in this project")
    receipt = TimeSeriesPortfolio.model_validate(record.selection)
    if receipt.project_id != project_id or record.selection_sha256 != digest or receipt.sha256() != digest:
        raise HTTPException(409, "Portfolio integrity check failed")
    for partition in receipt.partitions:
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        await require_trial_dataset_access(
            session=session,
            user_id=user_id,
            workflow_project_id=project_id,
            experiment_id=partition.experiment_id,
            stage="raw",
            file_id=partition.file_id,
            asset_id=partition.asset_id,
        )
        experiment = await _require_experiment(session, partition.experiment_id, user_id, "read")
        if experiment.project_id != project_id:
            raise HTTPException(403, "Portfolio source no longer belongs to this project")
        await _bosch_comparison_paths(
            session, partition.experiment_id, partition.file_id, partition.process_file_id, user_id
        )
    return record


async def build_portfolio(session, user_id, project_id, selections):
    observations = {}
    partitions = []
    for selection in selections:
        experiment = await _require_experiment(session, selection.experiment_id, user_id, "read")
        if experiment.project_id != project_id:
            raise HTTPException(403, "All portfolio sources must belong to this project")
        _, paths = await _bosch_comparison_paths(
            session, selection.experiment_id, selection.file_id, selection.process_file_id, user_id
        )
        # paths are confined application-owned records, not client paths.
        daily_path, process_path = paths
        if str(daily_path) not in observations:
            observations[str(daily_path)] = await asyncio.to_thread(bosch_phase_observations, daily_path)
        observed = observations[str(daily_path)]
        group = next((g for g in observed["groups"] if g["asset_id"] == selection.asset_id), None)
        if group is None:
            raise ValueError("Selected wafer is missing")
        process = builtin_registry.ingest(
            process_path, asset_id="Day_" + observed["date"].replace("-", "_") + "_" + selection.asset_id
        )
        labels, alignment = bosch_phases.phase_projection(
            group["times"], group["signal"], process.assets[0].dataset, retain_cycle_membership=True
        )
        cycles = np.asarray(alignment["cycle_indices"])
        production_membership = np.asarray(alignment["production_membership"])
        selected_phases = {
            "production": ["etch", "passivation"],
            "etch": ["etch"],
            "passivation": ["passivation"],
            "gas1": ["gas1_plasma"],
            "mixed": ["mixed_plasma"],
        }[selection.step_id]
        intervals = []
        # Split on process phase/cycle as well as recording gaps. Gaps do not increment cycles.
        cuts = (
            np.flatnonzero((labels[1:] != labels[:-1]) | (cycles[1:] != cycles[:-1]) | (np.diff(group["times"]) > 1))
            + 1
        )
        for run in np.split(np.arange(len(labels)), cuts):
            start, end = int(run[0]), int(run[-1])
            if (selection.step_id == "production" and production_membership[start]) or (
                selection.step_id != "production" and labels[start] in selected_phases
            ):
                intervals.append(
                    AcquisitionInterval(
                        first=start + 1, last=end + 1, phase=str(labels[start]), cycle=int(cycles[start]) or None
                    )
                )
        if not intervals:
            raise ValueError("The selected step has no recorded spectra")
        import json

        segmentation = hashlib.sha256(
            json.dumps(
                {
                    "algorithm": hashlib.sha256(Path(bosch_phases.__file__).read_bytes()).hexdigest(),
                    "alignment": alignment,
                    "intervals": [i.model_dump() for i in intervals],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        partitions.append(
            StepPartition(
                experiment_id=selection.experiment_id,
                file_id=selection.file_id,
                process_file_id=selection.process_file_id,
                source_sha256=observed["source_sha256"],
                process_sha256=process.source_members[0].sha256,
                oes_dictionary_sha256=dictionary_hash("Dictionary_OES.nc"),
                process_dictionary_sha256=dictionary_hash("Dictionary_process.nc"),
                segmentation_sha256=segmentation,
                day=observed["date"],
                wafer=selection.asset_id,
                asset_id=selection.asset_id,
                step_id=selection.step_id,
                recipe={
                    "production": "BOSCH",
                    "etch": "BOSCH · Etch",
                    "passivation": "BOSCH · Passivation",
                    "gas1": "Gas1-only plasma, identity unconfirmed",
                    "mixed": "Mixed plasma, unassigned",
                }[selection.step_id],
                intervals=tuple(intervals),
            )
        )
    return TimeSeriesPortfolio(project_id=project_id, partitions=tuple(partitions))
