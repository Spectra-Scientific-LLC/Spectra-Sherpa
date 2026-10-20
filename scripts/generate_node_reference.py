#!/usr/bin/env python3
"""Generate marked node reference sections from this checkout's live registry.

Run from the package root: python scripts/generate_node_reference.py [--check]
Only text between the markers is generated; methodology and examples are edited
by hand. Missing, duplicate, reversed, or orphaned markers fail before any write.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- BEGIN GENERATED NODE REFERENCE -->"
END = "<!-- END GENERATED NODE REFERENCE -->"
HELP_METADATA = "<!-- NODE HELP REFERENCES "
HELP_REFERENCE = re.compile(r"docs/nodes/(?:[a-z0-9][a-z0-9-]*/)*[a-z0-9][a-z0-9-]*\.md")
RECOVERY = "python scripts/generate_node_reference.py"


def load_registry() -> list[dict]:
    """Reuse catalog labels and census ports/contracts without booting the app."""
    sys.path.insert(0, str(ROOT / "tools"))
    from _provenance import ensure_local_checkout_on_path, require_local_checkout

    package_root = ensure_local_checkout_on_path(__file__)
    import spectra_sherpa

    require_local_checkout(package_root)
    if os.environ.get("SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION") == "1":
        raise ValueError("Unset SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION to load the complete built-in registry.")
    from spectra_sherpa.app.services.dag import node_registry
    from spectra_sherpa.app.services.dag.node_catalog_contract import build_node_contract_census

    # Keep the package import explicit for the provenance guard above.
    assert spectra_sherpa.__file__
    nodes = node_registry.list_catalog_nodes()
    census = build_node_contract_census(nodes)
    metadata = {node.node_type: node for node in nodes}
    if not metadata:
        raise ValueError("The built-in registry is empty.")
    return [
        {
            **row,
            "label": metadata[row["node_type"]].label,
            "parameters": [asdict(parameter) for parameter in metadata[row["node_type"]].parameters],
        }
        for row in census["nodes"]
    ]


def help_reference(row: dict) -> str:
    contract = row.get("execution_contract")
    reference = contract["payload"].get("help_reference") if contract else None
    if not isinstance(reference, str) or not HELP_REFERENCE.fullmatch(reference):
        raise ValueError(f"{row['node_type']}: missing or invalid node help_reference: {reference!r}")
    return reference


def cell(value: object) -> str:
    """Escape Markdown/HTML metacharacters, including pipes and multiline text."""
    return html.escape(str(value), quote=True).replace("|", "&#124;").replace("`", "&#96;").replace("\n", "<br>")


def code(value: object) -> str:
    return f"<code>{cell(value)}</code>"


def literal(value: object) -> str:
    return code(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def render_section(rows: list[dict]) -> str:
    references = {help_reference(row) for row in rows}
    if len(references) != 1:
        raise ValueError("A generated section must have exactly one contract help destination.")
    metadata = {
        "help_reference": references.pop(),
        "node_types": sorted(row["node_type"] for row in rows),
    }
    lines = [
        HELP_METADATA + json.dumps(metadata, sort_keys=True) + " -->",
        "",
        "## Registry reference",
        "",
        "Generated from registered node metadata. Edit methodology and examples outside the marked section.",
        "Defaults and options below are JSON values; `null` means no concrete default is declared.",
        "Internal parameters are retained for contract inspection and are not scientist-editable controls.",
        "Conditional visibility describes the editor; execution admission remains node-owned.",
        "",
    ]
    lines.extend(["| Node | Operation |", "| --- | --- |"])
    for row in sorted(rows, key=lambda item: item["node_type"]):
        lines.append(f"| {cell(row['label'])} | {code(row['node_type'])} |")
    lines.append("")
    for row in sorted(rows, key=lambda item: item["node_type"]):
        lines.extend([f"### {cell(row['label'])} (`{row['node_type']}`)", "", "#### Ports", ""])
        ports = row["typed_ports"]
        if not ports["inputs_declared"]:
            lines.extend(["Input ports are not declared.", ""])
        elif not ports["input_ports"]:
            lines.extend(["No input ports (source node).", ""])
        if not ports["outputs_declared"]:
            lines.extend(["Output ports are not declared.", ""])
        lines.extend(
            [
                "| Direction | Port | Type URI | Required | Variadic | Accepted data roles |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for direction in ("input", "output"):
            for port in ports[f"{direction}_ports"]:
                values = [
                    direction,
                    code(port["name"]),
                    code(port["type_ref"]),
                    literal(port["required"]),
                    literal(port["variadic"]),
                    literal(port["accepted_data_roles"]),
                ]
                lines.append("| " + " | ".join(values) + " |")
        lines.extend(["", "#### Parameters", ""])
        if not row["parameters"]:
            lines.extend(["No parameters.", ""])
            continue
        lines.extend(
            [
                "| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | "
                "Visibility / category | Description |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for parameter in row["parameters"]:
            bounds = {
                key: parameter[key] for key in ("min_value", "max_value", "step") if parameter.get(key) is not None
            }
            visibility = {key: parameter[key] for key in ("visible_when", "category") if parameter.get(key) is not None}
            description = " ".join(
                parameter[key] for key in ("description", "hint", "max_value_reason") if parameter.get(key)
            )
            values = [
                code(parameter["name"]),
                code(parameter["param_type"]),
                literal(parameter["required"]),
                literal(parameter["default"]),
                literal(parameter["options"]) if parameter.get("options") is not None else "—",
                literal(bounds) if bounds else "—",
                literal(visibility) if visibility else "—",
                cell(description) or "—",
            ]
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def replace_section(source: str, generated: str, path: Path) -> str:
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise ValueError(f"{path}: expected exactly one BEGIN and one END generated-node marker.")
    start = source.index(BEGIN) + len(BEGIN)
    end = source.index(END)
    if end < start:
        raise ValueError(f"{path}: generated-node markers are reversed.")
    return source[:start] + "\n\n" + generated + "\n" + source[end:]


def expected_documents(root: Path, rows: list[dict]) -> dict[Path, bytes]:
    groups: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        if row["node_type"] in seen:
            raise ValueError(f"Duplicate registry node: {row['node_type']}")
        seen.add(row["node_type"])
        groups[help_reference(row)].append(row)
    if not groups:
        raise ValueError("No node references to generate.")
    targets = {root / reference for reference in groups}
    for path in sorted((root / "docs/nodes").rglob("*.md")):
        source = path.read_text(encoding="utf-8")
        authored = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), "", source, flags=re.DOTALL)
        if re.search(r"^\|\s*Node\s*\|", authored, flags=re.MULTILINE):
            raise ValueError(
                f"{path}: handwritten node catalogue duplicates registry labels. "
                "Keep scientific guidance as prose and use the generated registry index."
            )
        if (BEGIN in source or END in source) and path not in targets:
            raise ValueError(f"{path}: orphaned generated-node markers; no registry help_reference targets this page.")
    documents = {}
    for reference, nodes in sorted(groups.items()):
        path = root / reference
        if not path.is_file():
            raise ValueError(f"{path}: missing node help page; create its methodology and the marker pair.")
        # Decode bytes rather than universal-newline reading: --check detects CRLF drift.
        source = path.read_bytes().decode("utf-8")
        documents[path] = replace_section(source, render_section(nodes), path).encode("utf-8")
    return documents


def generate(root: Path, rows: list[dict], *, check: bool) -> list[Path]:
    # Validate every page before writing any page.
    documents = expected_documents(root, rows)
    changed = [path for path, content in documents.items() if path.read_bytes() != content]
    if not check:
        for path in changed:
            path.write_bytes(documents[path])
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare exact bytes without modifying documentation.")
    args = parser.parse_args()
    # Imports may initialize runtime directories/caches. Keep them disposable,
    # and never write bytecode into the checkout during a check.
    sys.dont_write_bytecode = True
    with TemporaryDirectory(prefix="sherpa-node-reference-") as runtime:
        os.environ.update(DATA_DIR=runtime, MPLCONFIGDIR=f"{runtime}/mpl", APP_MODE="local", SITE_PROFILE="local")
        try:
            changed = generate(ROOT, load_registry(), check=args.check)
        except (ValueError, OSError) as error:
            print(f"Node reference refused: {error}", file=sys.stderr)
            print(
                f"Restore exactly one ordered marker pair in each contract help page:\n{BEGIN}\n{END}\n"
                "Remove markers from pages no longer targeted by a contract, preserving methodology.\n"
                f"Then, from the package root, run: {RECOVERY}",
                file=sys.stderr,
            )
            return 1
    if changed and args.check:
        print("Stale generated node reference: " + ", ".join(str(path.relative_to(ROOT)) for path in changed))
        print(f"From the package root, run: {RECOVERY}")
        return 1
    print(f"Node reference {'current' if args.check else 'generated'} ({len(changed)} changed pages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
