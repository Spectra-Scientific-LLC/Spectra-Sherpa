# Installation (OSS User)

SpectraSherpa is a local-first Python application. You can install it on your machine just like any other Python package.

## Quick Install

**Prerequisites:** Python 3.11 or higher.

```bash
pip install spectra-sherpa
```

## Launching the Application

Once installed, start the application from your terminal:

```bash
spectra-sherpa
```

This will:
1.  Start the local server on `http://localhost:8000`.
2.  Automatically open your default web browser.
3.  Initialize a local database in `~/.spectra_sherpa/`.

**No login is required.** In default "Local Mode", the application runs as a single-user desktop tool, similar to Jupyter Notebook.

## Command Line Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--port` | Server port | `8000` |
| `--no-browser` | Prevent browser from opening | `False` |
| `--data-dir` | Location for database and files | `~/.spectra_sherpa/` |

Example:
```bash
spectra-sherpa --port 9000 --no-browser
```
