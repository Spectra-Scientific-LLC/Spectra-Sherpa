from pathlib import Path

FRONTEND = Path(__file__).parents[1] / "frontend" / "src"
CANONICAL_IMPORT = "@/composables/useScientificPlotProjection"
CORE_IMPORT = "@/composables/scientificPlotProjectionCore"


def test_legacy_quick_plot_projection_module_is_retired() -> None:
    assert not (FRONTEND / "composables" / "usePlotData.ts").exists()
    for source in FRONTEND.rglob("*"):
        if source.suffix not in {".ts", ".vue"}:
            continue
        assert "@/composables/usePlotData" not in source.read_text(encoding="utf-8")


def test_renderer_core_is_private_to_the_canonical_facade() -> None:
    consumers = []
    for source in FRONTEND.rglob("*"):
        if source.suffix not in {".ts", ".vue"}:
            continue
        if CORE_IMPORT in source.read_text(encoding="utf-8"):
            consumers.append(source.relative_to(FRONTEND).as_posix())
    assert consumers == ["composables/useScientificPlotProjection.ts"]


def test_all_scientific_plot_surfaces_resolve_through_the_facade() -> None:
    expected_edges = {
        "canvas": (
            "views/workflow-builder/node-detail/composables/useNodePlotData.ts",
            CANONICAL_IMPORT,
        ),
        "quick_plot": (
            "views/workflow-builder/modals/QuickPlotModal.vue",
            CANONICAL_IMPORT,
        ),
        "run_details": (
            "views/models/RunDetailContent.vue",
            "QuickPlotModal",
        ),
        "reports": (
            "composables/useReportExport.ts",
            "scientificPlotImageTargets",
        ),
    }
    for surface, (relative_path, authority) in expected_edges.items():
        source = (FRONTEND / relative_path).read_text(encoding="utf-8")
        assert authority in source, f"{surface} bypasses canonical projection"
