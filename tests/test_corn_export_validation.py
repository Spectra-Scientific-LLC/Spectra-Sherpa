"""Manual qualification against the user's private registered Corn archive."""

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.skipif(not os.environ.get("CORN_ARCHIVE_PATH"), reason="requires user-acquired Corn archive and Jupyter")
@pytest.mark.asyncio
async def test_corn_exports(auth_client, test_session, test_user, tmp_path):
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.core.template_loader import TemplateLoader
    from spectra_sherpa.app.lib.reference_materialization import (
        materialize_reference_projection,
        portable_reference_manifest,
    )
    from spectra_sherpa.app.lib.registered_reference_storage import write_registered_reference_sidecar
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
    from spectra_sherpa.app.types import type_registry

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")
    output = Path(os.environ.get("CORN_EXPORT_PROOF_DIR", str(tmp_path / "exports")))
    output.mkdir(parents=True, exist_ok=True)
    archive_path = Path(os.environ["CORN_ARCHIVE_PATH"])
    private = archive_path.parent
    project = Project(user_id=test_user.id, name="Corn moisture export qualification")
    template = WorkflowTemplate(**next(t for t in TemplateLoader().load_all() if t["slug"] == "pls_calibration"))
    test_session.add_all([project, template])
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Corn M5", metadata_path="{}")
    test_session.add(experiment)
    await test_session.flush()
    source = settings.data_dir / "experiments" / f"exp_{experiment.id:03d}" / "raw/corn.mat"
    source.parent.mkdir(parents=True)
    materialize_reference_projection(archive_path, "public-corn-m5-moisture-v1", persist_member_to=source)
    write_registered_reference_sidecar(source, portable_reference_manifest("public-corn-m5-moisture-v1"))
    reference = output / "corn.mat"
    reference.write_bytes(source.read_bytes())
    file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/corn.mat",
        file_type="mat",
        stage="raw",
        file_size_bytes=source.stat().st_size,
    )
    test_session.add(file)
    await test_session.commit()
    from spectra_sherpa.app.lib.target_authority import issue_target_authority
    from spectra_sherpa.app.services.model_application import load_project_dataset

    loaded = await load_project_dataset(
        test_session, user_id=test_user.id, experiment_id=experiment.id, stage="raw", file_ids=[file.id]
    )
    authority = issue_target_authority(
        loaded.dataset,
        column="Moisture",
        target_type="continuous",
        source_digest=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    response = await auth_client.post(
        f"/api/v1/workflow-templates/{template.id}/instantiate",
        json={
            "workflow_name": "Corn Moisture PLS Export",
            "project_id": project.id,
            "data_bindings": {
                "data_1": {
                    "source": "experiment",
                    "experiment_id": experiment.id,
                    "file_id": file.id,
                    "stage": "raw",
                    "target_authority": authority.canonical_dict(),
                }
            },
        },
    )
    assert response.status_code == 201, response.text
    downloads = {}
    for fmt in ("python", "notebook", "zip"):
        r = await auth_client.get(f"/api/v1/workflows/{response.json()['id']}/export/download", params={"format": fmt})
        assert r.status_code == 200, r.text
        downloads[fmt] = r.content
    (output / "corn_export.zip").write_bytes(downloads["zip"])
    with zipfile.ZipFile(io.BytesIO(downloads["zip"])) as archive:
        assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in archive.namelist())
        archive.extractall(output)
        print("ZIP_CONTENTS", archive.namelist())
    bundle = next(output.glob("*/*_workflow.py")).parent
    (bundle / "direct_download.py").write_bytes(downloads["python"])
    (bundle / "direct_download.ipynb").write_bytes(downloads["notebook"])
    source.rename(source.with_suffix(".unavailable"))
    env = dict(
        os.environ,
        SHERPA_DATA_DIR=str(private),
        SPECTRA_REFERENCE_DIR=str(reference),
        MPLBACKEND="Agg",
        DATA_DIR=str(tmp_path / "empty-app"),
    )
    # Audit actual canonical results without changing the generated computation.
    inspect_code = """
import numpy as np
import json
def matrix(x):
    return np.asarray(x.X if hasattr(x, 'X') else x, dtype=float)
p = results['partition_1']
y = matrix(p['y_test']).reshape(-1)
pred = matrix(results['predict_1']['default']).reshape(-1)
err = pred-y
metrics = {'n_train': len(matrix(p['X_train'])), 'n_test': len(y),
           'n_features': matrix(p['X_train']).shape[1], 'rmsep': float(np.sqrt(np.mean(err**2))),
           'r2': float(1-np.sum(err**2)/np.sum((y-y.mean())**2)), 'bias': float(err.mean()),
           'sep': float(err.std(ddof=1)), 'target_min': float(y.min()), 'target_max': float(y.max())}
print('METRICS', metrics)
print('CANONICAL_EVALUATION', results['eval_1'])
assert len(y) == 20 and metrics['n_train'] == 60
assert np.isfinite(pred).all()
assert results['viz_1']['visualization']['data']
np.savez(RESULT_PATH, reference=y, predictions=pred, training=matrix(p['X_train']))
with open(RESULT_PATH + '.json', 'w') as f: json.dump(metrics, f, indent=2)
"""
    (output / "inspect_results.py").write_text(inspect_code)
    failures = {}
    for i, script in enumerate((bundle / "direct_download.py", next(bundle.glob("*_workflow.py")))):
        runner = (
            "import runpy; ns=runpy.run_path("
            + repr(str(script))
            + "); results=ns['run_workflow'](); RESULT_PATH="
            + repr(str(output / f"python-{i}.npz"))
            + "; exec("
            + repr(inspect_code)
            + ")"
        )
        run = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", runner],
            cwd=bundle,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (output / f"python-{i}.log").write_text(run.stdout + run.stderr)
        if run.returncode:
            failures[f"python-{i}"] = run.stderr
        cli = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(script)],
            cwd=bundle,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (output / f"cli-{i}.log").write_text(cli.stdout + cli.stderr)
        if cli.returncode:
            failures[f"cli-{i}"] = cli.stderr
    import nbformat
    from jupyter_client import KernelManager
    from nbclient import NotebookClient

    for i, notebook in enumerate((bundle / "direct_download.ipynb", next(bundle.glob("*_workflow.ipynb")))):
        nb = nbformat.read(notebook, as_version=4)
        nb.cells.append(
            nbformat.v4.new_code_cell("RESULT_PATH=" + repr(str(output / f"notebook-{i}.npz")) + "\n" + inspect_code)
        )
        km = KernelManager(kernel_name="python3")
        km.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
        client = NotebookClient(nb, km=km, timeout=120, resources={"metadata": {"path": str(bundle)}})
        try:
            await client.async_execute(env=env)
        except Exception as exc:
            failures[f"notebook-{i}"] = str(exc)
        finally:
            if km.has_kernel:
                await asyncio.to_thread(km.shutdown_kernel, now=True)
        nbformat.write(nb, notebook.with_name(notebook.stem + "-executed.ipynb"))
    (output / "failures.json").write_text(json.dumps(failures, indent=2))
    assert not failures, {name: value[-350:] for name, value in failures.items()}
    expected = np.load(output / "python-0.npz")
    for name in ("python-1", "notebook-0", "notebook-1"):
        actual = np.load(output / (name + ".npz"))
        for key in expected.files:
            np.testing.assert_allclose(actual[key], expected[key], rtol=1e-12, atol=1e-12)
    print("VERIFIED", (output / "python-0.npz.json").read_text())
