from spectra_sherpa.app.services.dataset_use import DatasetUseRecord, summarize_dataset_use


def test_renamed_and_exported_references_preserve_known_exposure():
    original = DatasetUseRecord(
        dataset_identity="same-content",
        label="Validation",
        basis="observed",
        results_revealed=True,
        influenced_development=True,
        source_receipt="receipt",
    )
    imported = DatasetUseRecord.model_validate(original.model_dump())
    renamed = DatasetUseRecord(
        dataset_identity="same-content",
        label="New independent test",
        basis="declared",
        results_revealed=False,
        influenced_development=False,
    )
    summary = summarize_dataset_use([imported, renamed])
    population = summary["populations"][0]
    assert len(summary["populations"]) == 1
    assert population["results_revealed"] is True
    assert population["influenced_development"] is True
    assert population["basis"] == "observed"
    assert population["labels"] == ["New independent test", "Validation"]
    assert summary["independence"] != "independent"


def test_unknown_history_and_distinct_unknown_records_do_not_imply_independence():
    assert summarize_dataset_use([])["independence"] == "not_established_by_usage_history"
    value = summarize_dataset_use([DatasetUseRecord(label="one"), DatasetUseRecord(label="one")])
    assert len(value["populations"]) == 2
    assert all(p["identity"] is None for p in value["populations"])
