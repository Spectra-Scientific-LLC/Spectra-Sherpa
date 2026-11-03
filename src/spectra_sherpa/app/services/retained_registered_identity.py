"""Read-only identity recovery from an exact registered split-input receipt.

This does not amend producer metadata or change runtime identity admission.
Only a direct, single-source split and its exact retained row mapping qualify.
"""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.array_identity import array_content_digest
from spectra_sherpa.app.lib.reference_artifacts import load_reference_artifact_registry
from spectra_sherpa.app.lib.reference_dataset_packages import package_view_projection, reference_annotation_table_digest
from spectra_sherpa.app.lib.reference_datasets import feature_axis_values_digest
from spectra_sherpa.app.lib.registered_reference_collection_identity import (
    validate_registered_reference_source_identity,
)
from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.sdk.dataset_identity import public_dataset_digest


class RegisteredIdentityUnavailable(ValueError):
    """A retained registered-source proof could not be re-admitted."""


def _need(ok, message):
    if not ok:
        raise RegisteredIdentityUnavailable(message)


class RetainedRegisteredIdentity:
    def __init__(self, definition, exact):
        self.definition = definition
        self.exact = exact
        self.roots = {}

    def _root(self, split, plan):
        if split in self.roots:
            return self.roots[split]
        from spectra_sherpa.app.services.paired_evaluation import restore_dataset

        inputs = [edge for edge in self.definition.get("edges", []) if edge.get("to_node_id") == split]
        _need(
            len(inputs) == 1 and inputs[0].get("to_input") in {None, "default", "X"},
            "Registered comparison requires one exact retained split input; multisource inputs are unavailable.",
        )
        edge = inputs[0]
        payload = self.exact(edge["from_node_id"], edge.get("from_output") or "default")
        try:
            root = restore_dataset(payload)
        except (ValueError, TypeError, KeyError):
            raise RegisteredIdentityUnavailable(
                "Registered split input does not reproduce its retained scientific receipt."
            ) from None
        source = root.meta.get("source_collection")
        try:
            validate_registered_reference_source_identity(source, root)
        except (ValueError, TypeError, KeyError):
            raise RegisteredIdentityUnavailable(
                "Retained registered source annotations do not reproduce their canonical source authority."
            ) from None
        _need(root.n_samples == plan["n_samples"], "Registered root and retained split counts differ.")
        _need(
            array_content_digest(np.asarray(root.data, dtype=float)) == plan["x_content_digest"],
            "Registered split input differs from the retained split feature receipt.",
        )
        registry = load_reference_artifact_registry()
        projection_id = root.get_extra("reference.projection_id")
        projection = registry.projection(projection_id).as_dict()
        _need(root.n_samples == projection["n_samples"], "Registered root size differs from its catalog projection.")
        artifact = registry.artifact(projection["artifact_id"]).as_dict()
        members = [item for item in artifact["members"] if item["path"] == projection["member_path"]]
        _need(len(members) == 1, "Registered artifact member is unavailable.")
        member = members[0]
        for key, value in {
            "reference.artifact_id": artifact["artifact_id"],
            "reference.artifact_sha256": artifact["sha256"],
            "reference.member_sha256": member["sha256"],
        }.items():
            _need(root.get_extra(key) == value, "Registered source differs from the governed artifact catalog.")
        files = source.get("files", [])
        _need(
            len(files) == 1
            and files[0].get("sha256") == member["sha256"]
            and files[0].get("size_bytes") == member["expected_size_bytes"],
            "Registered source member custody is missing or ambiguous.",
        )
        _need(
            len(root.meta.get("source_member_metadata") or []) <= 1,
            "Registered comparison cannot recover a mixed-source population.",
        )
        view = package_view_projection(projection_id)
        _need(
            view is not None and view["annotation_table"] is not None, "Registered annotation catalog is unavailable."
        )
        for key, value in {
            "reference.package_id": view["package_id"],
            "reference.view_id": view["view_id"],
            "reference.instrument_view": view["instrument"],
            "reference.cohort": view["cohort"],
            "reference.annotation_table_sha256": view["annotation_table"]["values_sha256"],
        }.items():
            _need(root.get_extra(key) == value, "Registered package annotations differ from the governed catalog.")
        ids = sample_ids(root)
        _need(ids is not None, "Registered root has no exact typed sample IDs.")
        table = root.sample_axis.sample_table
        fields = view["annotation_table"]["fields"]
        values = np.column_stack([table[field["name"]] for field in fields])
        _need(
            reference_annotation_table_digest(values, fields) == view["annotation_table"]["values_sha256"],
            "Registered response annotations do not reproduce their catalog receipt.",
        )
        _need(
            root.n_features == projection["n_features"]
            and feature_axis_values_digest(root.feature_axis.values) == projection["feature_axis_sha256"]
            and root.feature_axis.units == projection["feature_axis_units"]
            and root.feature_axis.title == projection["feature_axis_title"]
            and public_dataset_digest(root.data, table[projection["target_name"]]) == projection["scientific_sha256"],
            "Registered root scientific content or feature axis differs from its governed projection.",
        )
        context = root.target_context
        selected = context.selected_target or context.target_name
        if selected is None and len(context.target_names or []) == 1:
            selected = context.target_names[0]
        selected_fields = [field for field in fields if field["name"] == selected]
        _need(
            len(selected_fields) == 1 and context.target_units == selected_fields[0]["units"],
            "Registered selected response or units differ from the governed annotation column.",
        )
        self.roots[split] = root
        return root

    def ids(self, dataset, split, branch, plan):
        _need(branch in {"train", "test"}, "Registered comparison branch is unknown.")
        root = self._root(split, plan)
        indices = plan["train_indices" if branch == "train" else "test_indices"]
        raw = self.exact(split, "X_" + branch)
        _need(
            np.array_equal(np.asarray(raw.get("data"), dtype=float), np.asarray(root.data, dtype=float)[indices]),
            "Registered split feature rows differ from exact retained root indices.",
        )
        table = (dataset.get("y_axis") or {}).get("sample_table")
        expected = {name: [values[i] for i in indices] for name, values in root.sample_axis.sample_table.items()}
        _need(table == expected, "Registered branch sample IDs or annotations differ from exact split indices.")
        context = root.target_context
        selected = context.selected_target or context.target_name
        if selected is None and len(context.target_names or []) == 1:
            selected = context.target_names[0]
        _need(selected in expected, "Registered response column is not explicitly selected.")
        if dataset.get("target") is not None:
            _need(
                np.array_equal(
                    np.asarray(dataset["target"]).reshape(len(indices), -1),
                    np.asarray(expected[selected]).reshape(-1, 1),
                ),
                "Registered branch response values differ from its selected root annotation.",
            )
        source = (dataset.get("extra") or {}).get("source_collection") or {}
        _need(
            source == root.meta["source_collection"],
            "Registered branch source custody differs from its full retained root.",
        )
        entries = [
            entry
            for entry in dataset.get("provenance", [])
            if entry.get("op_id") == "data.train_test_split" and entry.get("node_id") == split
        ]
        _need(
            bool(entries)
            and entries[-1].get("parameters", {}).get("digest") == plan["digest"]
            and entries[-1].get("parameters", {}).get("split") == branch,
            "Registered branch has no matching retained split receipt.",
        )
        return list(table["sample_id"])

    def comparison_inputs(self, node, split, branch, plan, rows):
        """Do not erase a refusal contributed by an unrelated typed operand."""
        edges = [edge for edge in self.definition.get("edges", []) if edge.get("to_node_id") == node]
        ports = [edge.get("to_input") or "default" for edge in edges]
        _need(
            ports.count("default") == 1
            and ports.count("y_true") == 1
            and len(ports) == len(set(ports))
            and set(ports) <= {"default", "y_true", "sample_context"},
            "Registered comparison requires exact retained prediction and response input bindings.",
        )
        for edge, port in zip(edges, ports, strict=True):
            operand = self.exact(edge["from_node_id"], edge.get("from_output") or "default")
            typed = isinstance(operand, dict) and operand.get("type") == "SherpaDataset"
            if typed:
                self.ids(operand, split, branch, plan)
            if port == "sample_context":
                _need(typed, "Registered sample context is not an exact typed dataset.")
                continue
            values = operand.get("data") if typed else operand
            expected = [row["predicted" if port == "default" else "reference"] for row in rows]
            array = np.asarray(values, dtype=float)
            _need(
                array.shape in {(len(rows),), (len(rows), 1)} and np.array_equal(array.reshape(-1), expected),
                "Retained comparison values differ from their exact input binding.",
            )
