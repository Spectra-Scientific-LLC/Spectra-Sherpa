"""Canonical WebSocket action vocabulary shared across the platform.

**Source of truth for all WS actions.**  Both the frontend (``sherpaWs.ts``)
and the server (``register_sherpa_ws_actions``) reference these constants.

To add a new Sherpa action:
1. Define the constant here.
2. Add it to ``SHERPA_WS_ACTIONS``.
3. Add the matching key in ``frontend/src/lib/sherpaWs.ts → SHERPA_WS_ACTION``.
4. Register the handler in the commercial server's WS registrar.
5. Run ``pytest tests/test_ws_contract.py`` — it will fail until all three are in sync.
"""

LLM_CHAT = "llm_chat"

SHERPA_SYNC = "sherpa_sync"
SHERPA_DECIDE = "sherpa_decide"
SHERPA_CHAT = "sherpa_chat"
SHERPA_IDENTIFY_PEAKS = "sherpa_identify_peaks"
SHERPA_GENERATE_CODE = "sherpa_generate_code"
SHERPA_WRITE_REPORT = "sherpa_write_report"
SHERPA_DATA_STORY = "sherpa_data_story"
SHERPA_CHAT_WITH_TOOLS = "sherpa_chat_with_tools"

CORE_WS_ACTIONS: tuple[str, ...] = (LLM_CHAT,)

SHERPA_WS_ACTIONS: tuple[str, ...] = (
    SHERPA_SYNC,
    SHERPA_DECIDE,
    SHERPA_CHAT,
    SHERPA_IDENTIFY_PEAKS,
    SHERPA_GENERATE_CODE,
    SHERPA_WRITE_REPORT,
    SHERPA_DATA_STORY,
    SHERPA_CHAT_WITH_TOOLS,
)
