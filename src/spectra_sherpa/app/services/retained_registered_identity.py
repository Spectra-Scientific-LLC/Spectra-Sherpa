"""Read-only identity recovery from an exact registered split-input receipt.

This does not amend producer metadata or change runtime identity admission.
A direct source or one retained penalized baseline may precede the split.
The catalog source and the actual split input are verified separately.
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
        self.source_inputs = {}

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
        split_input = root
        _need(root.n_samples == plan["n_samples"], "Registered root and retained split counts differ.")
        _need(
            array_content_digest(np.asarray(root.data, dtype=float)) == plan["x_content_digest"],
            "Registered split input differs from the retained split feature receipt.",
        )
        nodes = {node["node_id"]: node for node in self.definition.get("nodes", [])}
        producer = nodes.get(edge["from_node_id"], {})
        source_payload = payload
        if producer.get("node_type") == "baseline.penalized_ls":
            from spectra_sherpa.app.services.dag.nodes.preprocessing.penalized_baseline_node import (
                BaselinePenalizedLSNode,
            )

            parents = [e for e in self.definition.get("edges", []) if e.get("to_node_id") == edge["from_node_id"]]
            _need(
                (edge.get("from_output") or "default") == "default"
                and len(parents) == 1
                and parents[0].get("to_input") in {None, "default"}
                and nodes.get(parents[0]["from_node_id"], {}).get("node_type")
                in {"data.file_load", "data.collection_load"}
                and (parents[0].get("from_output") or "default") == "default",
                "Registered baseline comparison requires one direct retained file source.",
            )
            source_payload = self.exact(parents[0]["from_node_id"], "default")
            try:
                root = restore_dataset(source_payload)
            except (ValueError, TypeError, KeyError):
                raise RegisteredIdentityUnavailable(
                    "Registered baseline source scientific receipt is unavailable."
                ) from None
            history = root.provenance.to_list()
            corrected_history = split_input.provenance.to_list()
            _need(
                len(corrected_history) == len(history) + 1 and corrected_history[:-1] == history,
                "Retained baseline does not extend its exact source provenance.",
            )
            step = corrected_history[-1]
            _need(
                step.get("op_id") == "baseline.penalized_ls"
                and step.get("node_id") == edge["from_node_id"]
                and step.get("parameters")
                == BaselinePenalizedLSNode.metadata.canonicalize_parameters(producer.get("parameters", {})),
                "Retained baseline provenance differs from the saved workflow.",
            )
            _need(
                split_input.shape == root.shape
                and split_input.sample_axis.model_dump(mode="json") == root.sample_axis.model_dump(mode="json")
                and split_input.feature_axis.model_dump(mode="json") == root.feature_axis.model_dump(mode="json")
                and split_input.target_context == root.target_context
                and np.array_equal(split_input.target, root.target)
                and split_input.meta.get("source_collection") == root.meta.get("source_collection"),
                "Retained baseline changed registered rows, response, axes or source custody.",
            )
        source = root.meta.get("source_collection")
        try:
            validate_registered_reference_source_identity(source, root)
        except (ValueError, TypeError, KeyError):
            raise RegisteredIdentityUnavailable(
                "Retained registered source annotations do not reproduce their canonical source authority."
            ) from None
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
        self.source_inputs[split] = source_payload
        self.roots[split] = split_input
        return split_input

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
