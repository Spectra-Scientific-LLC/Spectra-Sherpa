"""Contract tests for the WebSocket action vocabulary.

Three groups of assertions:

1. **Naming conventions** — every action name in ``CORE_WS_ACTIONS`` and
   ``SHERPA_WS_ACTIONS`` is lowercase snake_case; sherpa-namespaced
   actions are prefixed with ``sherpa_``; core actions are not.

2. **Registry coverage** — ``build_default_ws_action_registry()`` (the
   OSS default) registers every name in ``CORE_WS_ACTIONS`` and none of
   the names in ``SHERPA_WS_ACTIONS``. Sherpa actions are owned by the
   commercial server's startup hooks.

3. **Frontend references only known actions** — every value in
   ``SHERPA_WS_ACTION`` in ``frontend/src/lib/sherpaWs.ts`` belongs to
   the union of the two backend-defined sets. (Exact alignment between
   frontend keys and backend constants is covered by the existing
   ``tests/test_ws_contract.py``; this test is the looser invariant.)
"""

from __future__ import annotations

import re
from pathlib import Path

from spectra_sherpa.app.services.ws_action_registry import build_default_ws_action_registry
from spectra_sherpa.app.ws_actions import CORE_WS_ACTIONS, SHERPA_WS_ACTIONS

ALL_BACKEND_ACTIONS: frozenset[str] = frozenset(CORE_WS_ACTIONS) | frozenset(SHERPA_WS_ACTIONS)

# snake_case: lowercase letters, digits, underscores; must start with a letter.
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

FRONTEND_WS_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "sherpaWs.ts"


# ── 1. Naming conventions ─────────────────────────────────────────────


class TestNamingConventions:
    def test_core_actions_are_snake_case(self) -> None:
        for name in CORE_WS_ACTIONS:
            assert _SNAKE_CASE_RE.match(name), f"core action {name!r} is not snake_case"

    def test_sherpa_actions_are_snake_case(self) -> None:
        for name in SHERPA_WS_ACTIONS:
            assert _SNAKE_CASE_RE.match(name), f"sherpa action {name!r} is not snake_case"

    def test_sherpa_actions_have_sherpa_prefix(self) -> None:
        for name in SHERPA_WS_ACTIONS:
            assert name.startswith(
                "sherpa_"
            ), f"action {name!r} is in SHERPA_WS_ACTIONS but does not start with 'sherpa_'"

    def test_core_actions_do_not_have_sherpa_prefix(self) -> None:
        for name in CORE_WS_ACTIONS:
            assert not name.startswith(
                "sherpa_"
            ), f"action {name!r} is in CORE_WS_ACTIONS but uses the sherpa_ namespace"

    def test_no_duplicates_within_sets(self) -> None:
        assert len(CORE_WS_ACTIONS) == len(set(CORE_WS_ACTIONS)), "CORE_WS_ACTIONS has duplicates"
        assert len(SHERPA_WS_ACTIONS) == len(set(SHERPA_WS_ACTIONS)), "SHERPA_WS_ACTIONS has duplicates"

    def test_no_overlap_between_sets(self) -> None:
        overlap = set(CORE_WS_ACTIONS) & set(SHERPA_WS_ACTIONS)
        assert not overlap, f"actions appear in both CORE and SHERPA: {sorted(overlap)}"


# ── 2. Registry coverage ──────────────────────────────────────────────


class TestRegistryCoverage:
    def test_default_registry_includes_every_core_action(self) -> None:
        registered = set(build_default_ws_action_registry().names())
        missing = set(CORE_WS_ACTIONS) - registered
        assert not missing, (
            f"OSS default WS registry is missing core actions: {sorted(missing)}. "
            "Either register them in register_core_ws_actions() or move them out "
            "of CORE_WS_ACTIONS."
        )

    def test_default_registry_does_not_register_sherpa_actions(self) -> None:
        """Sherpa actions are owned by the commercial server's startup."""
        registered = set(build_default_ws_action_registry().names())
        leaked = registered & set(SHERPA_WS_ACTIONS)
        assert not leaked, (
            f"OSS default registry registers sherpa-namespaced actions: {sorted(leaked)}. "
            "Sherpa actions must be registered by the server, not by OSS."
        )

    def test_default_registry_only_uses_known_action_names(self) -> None:
        """Sanity check — registered names should be in the documented vocabulary."""
        registered = set(build_default_ws_action_registry().names())
        unknown = registered - ALL_BACKEND_ACTIONS
        assert not unknown, (
            f"OSS default registry registers actions not declared in ws_actions.py: " f"{sorted(unknown)}"
        )


# ── 3. Frontend references only known actions ────────────────────────


def _extract_frontend_action_values() -> set[str]:
    source = FRONTEND_WS_PATH.read_text()
    match = re.search(r"export const SHERPA_WS_ACTION = \{(.*?)\} as const;", source, re.DOTALL)
    assert match is not None, (
        f"Could not find SHERPA_WS_ACTION in {FRONTEND_WS_PATH}. "
        "Did the frontend file move? Update FRONTEND_WS_PATH."
    )
    return {value for _key, value in re.findall(r'(\w+):\s*"([^"]+)"', match.group(1))}


class TestFrontendVocabulary:
    def test_frontend_references_only_known_actions(self) -> None:
        frontend_values = _extract_frontend_action_values()
        unknown = frontend_values - ALL_BACKEND_ACTIONS
        assert not unknown, (
            f"frontend sherpaWs.ts references actions not declared in the backend "
            f"vocabulary: {sorted(unknown)}. Add them to CORE_WS_ACTIONS or "
            f"SHERPA_WS_ACTIONS, or remove them from the frontend."
        )
