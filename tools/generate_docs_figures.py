#!/usr/bin/env python3
"""Generate the static concept figures used by the user documentation.

Every figure is synthetic and deterministic: no provider data, no user data,
no measurements. Each image states in its caption that it is illustrative.
Run from the package root:

    python tools/generate_docs_figures.py

Figures are written to docs/assets/ and committed; regenerate on change and
review the pixel diff like any other documentation change.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

ASSETS = Path(__file__).resolve().parents[1] / "docs" / "assets"
RNG = np.random.default_rng(20261020)

INK = "#334155"
MUTED = "#94a3b8"
ACCENT = "#3b82f6"
WARM = "#f59e0b"
DANGER = "#ef4444"


def _style(ax: plt.Axes) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(colors=INK, labelsize=9)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(MUTED)


def workflow_canvas_map() -> None:
    """Numbered schematic of the Workflow Builder layout (not a screenshot)."""
    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=150)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")

    def box(x: float, y: float, w: float, h: float, label: str, fc: str) -> None:
        ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=fc, edgecolor=INK, linewidth=1.2, zorder=2))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=9, color=INK, zorder=3)

    def callout(n: int, x: float, y: float) -> None:
        ax.add_patch(plt.Circle((x, y), 0.21, facecolor=ACCENT, edgecolor="none", zorder=4))
        ax.text(x, y, str(n), ha="center", va="center", fontsize=10, color="white", weight="bold", zorder=5)

    box(0.2, 5.0, 9.6, 0.8, "Top bar:  Analysis Starter · Run · Save · Compare runs · Export · Audit", "#f1f5f9")
    box(0.2, 0.6, 2.3, 4.2, "Add Nodes /\nNode Catalog\n\nsearch + categories\n\nclick a node to add it", "#e2e8f0")
    box(2.7, 0.6, 4.6, 4.2, "Canvas\n\nnodes appear as cards\n\nclick an output port,\nthen an input port, to connect", "#ffffff")
    box(7.5, 0.6, 2.3, 4.2, "Inspector\n\nparameters, help,\ninput/output preview\nfor the selected node", "#e2e8f0")

    callout(1, 0.55, 4.45)
    callout(2, 3.05, 4.45)
    callout(3, 7.85, 4.45)
    callout(4, 0.55, 5.4)

    ax.text(0.2, 0.2, "1 add a node    2 connect its ports    3 set its parameters    4 Run (top bar)",
            fontsize=9, color=INK)

    fig.tight_layout()
    fig.savefig(ASSETS / "workflow-canvas-map.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def pca_scores_loadings() -> None:
    """Two-panel PCA concept: score map and loading vector (synthetic)."""
    x = np.linspace(4000, 400, 400)  # cm-1, high to low as convention
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.5, 3.8), dpi=150)

    g1 = RNG.normal(loc=(-1.6, 0.9), scale=(0.55, 0.45), size=(24, 2))
    g2 = RNG.normal(loc=(1.7, -0.7), scale=(0.6, 0.5), size=(24, 2))
    ax1.scatter(g1[:, 0], g1[:, 1], c=ACCENT, s=28, label="batch A", zorder=3)
    ax1.scatter(g2[:, 0], g2[:, 1], c=WARM, s=28, marker="s", label="batch B", zorder=3)
    ax1.scatter([3.4], [2.6], c=DANGER, s=42, marker="X", label="possible outlier", zorder=3)
    ax1.set_xlabel("PC 1 score")
    ax1.set_ylabel("PC 2 score")
    ax1.set_title("Scores: how samples relate", fontsize=10, color=INK)
    ax1.legend(fontsize=8, frameon=False)
    _style(ax1)

    loading = (
        np.exp(-((x - 1735) ** 2) / (2 * 28**2))
        - 0.8 * np.exp(-((x - 2930) ** 2) / (2 * 45**2))
        + 0.25 * RNG.normal(size=x.size)
    )
    ax2.plot(x, loading, color=INK, linewidth=1.1)
    ax2.axhline(0, color=MUTED, linewidth=0.8)
    ax2.set_xlabel("wavenumber (cm$^{-1}$)")
    ax2.set_ylabel("PC 1 loading")
    ax2.set_title("Loadings: which spectral regions drive it", fontsize=10, color=INK)
    _style(ax2)

    fig.tight_layout()
    fig.savefig(ASSETS / "pca-scores-loadings.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def specimen_split() -> None:
    """Why specimen identity matters for a held-out test set."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.5, 3.4), dpi=150, sharey=True)
    specimens = [f"S{i}" for i in range(1, 9)]
    rows = []
    for s in specimens:
        rows.extend([s] * 3)  # three replicate spectra per specimen

    for ax, mode in ((ax1, "leak"), (ax2, "clean")):
        for i, s in enumerate(rows):
            if mode == "leak":
                test = RNG.random() < 0.3
            else:
                test = s in {"S7", "S8"}
            color = WARM if test else ACCENT
            ax.scatter(0.5 + RNG.normal(0, 0.06), i, c=color, s=26, zorder=3)
            ax.text(0.05, i, s, fontsize=8, va="center", color=INK)
        ax.set_xlim(0, 1)
        ax.set_xticks([])
        ax.set_ylim(-1, len(rows))
        ax.invert_yaxis()
        title = (
            "Naive row split: replicates of one\nspecimen land in both sides (leakage)"
            if mode == "leak"
            else "Specimen holdout: all replicates of a\nspecimen stay together (honest test)"
        )
        ax.set_title(title, fontsize=9.5, color=INK)
        _style(ax)
        ax.spines["left"].set_visible(False)
        ax.set_yticks([])
    ax1.scatter([], [], c=ACCENT, s=26, label="calibration")
    ax1.scatter([], [], c=WARM, s=26, label="held-out test")
    ax1.legend(fontsize=8, frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(ASSETS / "specimen-holdout.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def snv_before_after() -> None:
    """Scatter correction concept: raw spectra vs the same spectra after SNV."""
    x = np.linspace(4000, 400, 300)
    base = (
        np.exp(-((x - 1650) ** 2) / (2 * 60**2))
        + 0.7 * np.exp(-((x - 2920) ** 2) / (2 * 40**2))
        + 0.4 * np.exp(-((x - 3400) ** 2) / (2 * 120**2))
    )
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.5, 3.4), dpi=150, sharex=True)
    for ax, corrected in ((ax1, False), (ax2, True)):
        for i in range(6):
            spectrum = base * (0.8 + 0.08 * i) + (0.15 * i if not corrected else 0.0)
            if corrected:
                spectrum = (spectrum - spectrum.mean()) / spectrum.std()
            ax.plot(x, spectrum, linewidth=0.9, alpha=0.85)
        ax.set_title("Raw spectra: offset and scale drift" if not corrected else "After SNV: comparable shape", fontsize=10, color=INK)
        _style(ax)
    ax1.set_xlabel("wavenumber (cm$^{-1}$)")
    ax2.set_xlabel("wavenumber (cm$^{-1}$)")
    ax1.set_ylabel("absorbance (a.u.)")
    fig.tight_layout()
    fig.savefig(ASSETS / "preprocessing-snv.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def pls_calibration_fit() -> None:
    """Predicted vs measured with calibration and held-out samples separated."""
    true = np.linspace(2, 18, 40)
    cal = RNG.normal(true, 0.55)
    true_test = np.linspace(3, 17, 12)
    test = RNG.normal(true_test, 0.85)
    fig, ax = plt.subplots(figsize=(5.2, 4.4), dpi=150)
    ax.scatter(true, cal, c=ACCENT, s=26, label="calibration (CV)", zorder=3)
    ax.scatter(true_test, test, c=WARM, s=34, marker="s", label="held-out test", zorder=3)
    lim = (1, 19)
    ax.plot(lim, lim, color=MUTED, linewidth=1.0, linestyle="--", label="ideal: predicted = measured")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("measured (reference) value")
    ax.set_ylabel("predicted value")
    ax.set_title("A calibration you can trust separates\ncalibration fit from held-out performance", fontsize=9.5, color=INK)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(ASSETS / "pls-predicted-vs-measured.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    workflow_canvas_map()
    pca_scores_loadings()
    specimen_split()
    snv_before_after()
    pls_calibration_fit()
    print(f"Wrote 5 figures to {ASSETS}")


if __name__ == "__main__":
    main()
