#!/usr/bin/env python3
"""Check static source references before spending on standalone CI matrices.

This is a stdlib-only existence/selector gate, not a shell interpreter. Dynamic
artifact paths and external URLs still require the normal execution gates.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

SOURCE_REFERENCE = re.compile(
    r"(?<![\w/])((?:tests|scripts|tools|desktop)/[\w./*-]+\.(?:py|ps1|cjs|mjs|js|sh))" r"((?:::[\w]+)*)(?![\w.])"
)


def audit(root: Path) -> dict[str, object]:
    root = root.resolve()
    failures: list[str] = []
    checked: set[tuple[str, str]] = set()

    def reference(source: Path, relative: str, base: Path = root) -> list[Path]:
        label = source.relative_to(root).as_posix()
        checked.add((label, relative))
        paths = list(base.glob(relative)) if "*" in relative else [base / relative]
        if any(not path.resolve().is_relative_to(root) for path in paths):
            failures.append(f"{label}: reference escapes standalone package: {relative}")
            return []
        if not paths or not all(path.exists() for path in paths):
            failures.append(f"{label}: missing {relative}")
            return []
        return paths

    workflows = sorted((root / ".github/workflows").glob("*.yml"))
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for match in SOURCE_REFERENCE.finditer(text.replace("\\", "/")):
            relative, selector = match.groups()
            paths = reference(workflow, relative)
            for path in paths if selector else []:
                nodes = ast.parse(path.read_text(encoding="utf-8")).body
                for name in selector.removeprefix("::").split("::"):
                    found = next((node for node in nodes if getattr(node, "name", None) == name), None)
                    if found is None:
                        failures.append(f"{workflow.name}: missing selector {relative}{selector}")
                        break
                    nodes = getattr(found, "body", [])
        for relative in re.findall(r"^\s*working-directory:\s*([\w./-]+)\s*$", text, re.MULTILINE):
            reference(workflow, relative)
        for relative in re.findall(r"uses:\s*(\./[\w./-]+)", text):
            reference(workflow, relative)
        for relative in re.findall(r"config_file:\s*([\w./-]+)", text):
            reference(workflow, relative)

    for relative in ("frontend/package.json", "desktop/electron/package.json"):
        package_file = root / relative
        package = json.loads(package_file.read_text(encoding="utf-8"))
        if package.get("main"):
            reference(package_file, package["main"], package_file.parent)
        for command in package.get("scripts", {}).values():
            for script in re.findall(r"\bnode\s+(?:--[\w-]+\s+)*([\w./*-]+\.(?:cjs|mjs|js))(?![\w.])", command):
                reference(package_file, script, package_file.parent)
            for schema in re.findall(r"\bopenapi-typescript\s+([\w./-]+\.json)", command):
                reference(package_file, schema, package_file.parent)

    project_path = root / "pyproject.toml"
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))
    for entry in project["tool"]["poetry"].get("scripts", {}).values():
        module, _, symbol = entry.partition(":")
        relative = "src/" + module.replace(".", "/") + ".py"
        for path in reference(project_path, relative):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if symbol and not any(getattr(node, "name", None) == symbol for node in tree.body):
                failures.append(f"pyproject.toml: missing entry point {entry}")

    documents = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    links = 0
    for document in documents:
        for raw in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = unquote(raw.strip().split()[0].strip("<>").split("#")[0])
            if not target or re.match(r"^[\w+.-]+:", target) or target.startswith(("/", "$", "{")):
                continue
            links += 1
            reference(document, target, document.parent)
    return {
        "workflows": len(workflows),
        "documents": len(documents),
        "local_document_links": links,
        "unique_references": len(checked),
        "failures": sorted(set(failures)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = audit(args.package_root)
    print(json.dumps(result, indent=2))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
