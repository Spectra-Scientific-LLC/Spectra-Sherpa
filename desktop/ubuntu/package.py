#!/usr/bin/env python3
"""Build one pinned x86-64 AppImage from the already hardened Electron bundle."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]


def fetch_tool(record: dict, path: Path) -> Path:
    if not path.exists():
        with urllib.request.urlopen(record["url"], timeout=120) as response:
            path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"Checksum mismatch for {path.name}; refusing to execute")
    path.chmod(0o755)
    return path


def stage(source: Path, destination: Path) -> None:
    if not (source / "resources/app.asar").is_file() or not (source / "SpectraSherpa").is_file():
        raise ValueError("Require the packaged Electron application")
    shutil.copytree(source, destination, symlinks=True)
    shutil.copy2(HERE / "AppRun", destination / "AppRun")
    (destination / "AppRun").chmod(0o755)
    (destination / "spectrasherpa.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Spectra Sherpa\nExec=SpectraSherpa %U\n"
        "Icon=spectrasherpa\nCategories=Science;Education;\nTerminal=false\n"
    )
    shutil.copy2(PACKAGE / "frontend/public/logo.png", destination / "spectrasherpa.png")


def main():
    if (platform.system(), platform.machine()) != ("Linux", "x86_64"):
        raise ValueError("Build Ubuntu AppImage on Linux x86-64")
    output = PACKAGE / "desktop/dist"
    cache = output / "appimage-tools"
    cache.mkdir(parents=True, exist_ok=True)
    tools = json.loads((HERE / "tools.json").read_text())
    tool = fetch_tool(tools["appimagetool"], cache / "appimagetool")
    runtime = fetch_tool(tools["runtime"], cache / "runtime")
    appdir = output / "SpectraSherpa.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    stage(PACKAGE / "desktop/electron/out/SpectraSherpa-linux-x64", appdir)
    subprocess.run(
        [str(tool), "--runtime-file", str(runtime), str(appdir), str(output / "SpectraSherpa.AppImage")],
        env={**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"},
        check=True,
    )


if __name__ == "__main__":
    main()
