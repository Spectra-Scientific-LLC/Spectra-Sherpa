#!/usr/bin/env python3
"""
One-time conversion script: extract WORKFLOW_TEMPLATES from Python dicts
into individual YAML files with schema_version and data_roles.

Usage:
    cd <repo-root>
    python scripts/convert_templates_to_yaml.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the source tree is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml  # noqa: E402

from spectra_sherpa.app.core.workflow_templates import WORKFLOW_TEMPLATES  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "data" / "templates"


def _infer_data_roles(slug: str, category: str, user_dataset_mode: dict) -> dict:
    """Derive data_roles from user_dataset_mode and template category."""
    roles: dict[str, dict] = {}

    # Count source nodes to determine binding patterns
    source_nodes = list(user_dataset_mode.keys())

    for node_id, mode in user_dataset_mode.items():
        requires_target = mode.get("requires_target", False)
        technique = mode.get("technique", [])
        description = mode.get("description", "")

        # Primary spectral data role
        if not requires_target:
            role_key = "X_spectra"
            roles[role_key] = {
                "role_type": "X_spectra",
                "node_binding": node_id,
                "required": True,
                "binding_mode": "embedded",
                "description": description or "Spectral data matrix",
            }
            if technique:
                roles[role_key]["accepted_techniques"] = technique

        elif requires_target:
            # Check if this is a separate target source node (multi-source templates)
            # vs a single-source node with embedded target
            is_separate_target = len(source_nodes) > 1

            if is_separate_target:
                # This node is a dedicated target/reference data source
                if category in ("classification", "quality_control"):
                    role_key = "class_labels"
                    roles[role_key] = {
                        "role_type": "class_labels",
                        "node_binding": node_id,
                        "required": True,
                        "binding_mode": "separate_source",
                        "target_type": "categorical",
                        "description": description or "Classification labels",
                    }
                else:
                    role_key = "Y_reference"
                    roles[role_key] = {
                        "role_type": "Y_reference",
                        "node_binding": node_id,
                        "required": True,
                        "binding_mode": "separate_source",
                        "target_type": "continuous",
                        "description": description or "Reference values",
                    }
            else:
                # Single-source with embedded target
                # The X_spectra role should already be set, add a Y/class role
                # First, set X_spectra if not already set
                if "X_spectra" not in roles:
                    roles["X_spectra"] = {
                        "role_type": "X_spectra",
                        "node_binding": node_id,
                        "required": True,
                        "binding_mode": "embedded",
                        "description": description or "Spectral data matrix",
                    }
                    if technique:
                        roles["X_spectra"]["accepted_techniques"] = technique

                if category in ("classification", "quality_control"):
                    roles["class_labels"] = {
                        "role_type": "class_labels",
                        "node_binding": node_id,
                        "required": True,
                        "binding_mode": "embedded",
                        "target_type": "categorical",
                        "description": "Classification labels (column in spectral data file)",
                    }
                else:
                    roles["Y_reference"] = {
                        "role_type": "Y_reference",
                        "node_binding": node_id,
                        "required": True,
                        "binding_mode": "embedded",
                        "target_type": "continuous",
                        "description": "Reference/target values (column in spectral data file)",
                    }

    return roles


def _build_yaml_dict(template: dict) -> dict:
    """Convert a single Python template dict to the YAML schema format."""
    td = template["template_data"]
    user_dataset_mode = td.get("user_dataset_mode", {})

    # Build data_roles from user_dataset_mode
    data_roles = _infer_data_roles(
        slug=template["slug"],
        category=template["category"],
        user_dataset_mode=user_dataset_mode,
    )

    # Build template_data preserving structure
    template_data: dict = {
        "nodes": td["nodes"],
        "edges": td["edges"],
        "canvas_state": td.get("canvas_state", {"zoom": 1.0, "pan_x": 0, "pan_y": 0}),
        "user_dataset_mode": user_dataset_mode,
    }
    if data_roles:
        template_data["data_roles"] = data_roles

    return {
        "schema_version": 1,
        "name": template["name"],
        "slug": template["slug"],
        "description": template["description"],
        "category": template["category"],
        "is_active": template.get("is_active", True),
        "template_data": template_data,
    }


class _FlowStyleDumper(yaml.SafeDumper):
    """Custom YAML dumper for compact parameter/position representation."""

    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Use literal block style for multi-line strings, plain otherwise."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_FlowStyleDumper.add_representer(str, _str_representer)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for template in WORKFLOW_TEMPLATES:
        slug = template["slug"]
        yaml_dict = _build_yaml_dict(template)
        out_path = OUTPUT_DIR / f"{slug}.yaml"
        with open(out_path, "w") as f:
            yaml.dump(
                yaml_dict,
                f,
                Dumper=_FlowStyleDumper,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
        print(f"  wrote {out_path.name}")

    print(f"\nConverted {len(WORKFLOW_TEMPLATES)} templates to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
