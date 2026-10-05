"""Exercise local reference imports through the same endpoints as My Dataset."""

import pytest
from httpx import AsyncClient

from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG


@pytest.mark.anyio
@pytest.mark.parametrize(
    "source,name",
    [("sklearn", name) for name in ("iris", "wine", "breast_cancer")]
    + [("synthetic", name) for name in SYNTHETIC_REFERENCE_CATALOG]
    + [("oes", "uvspectra10")],
)
async def test_builtin_import_inspection_and_persisted_matrix(auth_client: AsyncClient, source: str, name: str):
    project = (await auth_client.post("/api/v1/projects", json={"name": name})).json()
    experiment = (
        await auth_client.post("/api/v1/experiments", json={"name": name, "project_id": project["id"]})
    ).json()
    imported = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-reference",
        json={"datasets": [{"source": source, "name": name}]},
    )
    assert imported.status_code == 201, imported.text
    experiment_id = imported.json().get("experiment_id") or experiment["id"]
    files = (await auth_client.get(f"/api/v1/experiments/{experiment_id}/files")).json()
    assert len(files) == 1
    info = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": experiment_id})
    assert info.status_code == 200, info.text
    dataset = info.json()
    matrix_response = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={"kind": "experiment_file", "experiment_id": experiment_id, "file_id": files[0]["id"]},
    )
    assert matrix_response.status_code == 200, matrix_response.text
    matrix = matrix_response.json()
    assert dataset["n_samples"] > 0
    assert dataset["n_features"] > 0
    assert matrix["total_rows"] == dataset["n_samples"]
    assert matrix["total_cols"] == dataset["n_features"]
    assert len(matrix["row_labels"]) == len(matrix["matrix"])
    assert len(matrix["col_labels"]) == len(matrix["matrix"][0])
    reference_response = await auth_client.post(
        "/api/v1/builder/data-matrix", json={"kind": "reference", "source": source, "name": name}
    )
    assert reference_response.status_code == 200, reference_response.text
    reference = reference_response.json()
    for key in ("shape", "col_labels", "matrix"):
        assert matrix.get(key) == reference.get(key), f"{source}:{name} changed {key} on import"
    if source != "sklearn":
        assert matrix.get("row_labels") == reference.get("row_labels")
        assert matrix.get("target") == reference.get("target")
    if source == "sklearn":
        expected = {"iris": (150, 4), "wine": (178, 13), "breast_cancer": (569, 30)}
        assert (dataset["n_samples"], dataset["n_features"]) == expected[name]
        assert dataset["data_role"] == "X_features"
        assert matrix["target"]["target_type"] == "categorical"
        assert matrix["target"]["n_classes"] == reference["target"]["n_classes"]
        assert sorted((item["label"], item["count"]) for item in matrix["target"]["classes"]) == sorted(
            (item["label"], item["count"]) for item in reference["target"]["classes"]
        )
