"""Canonical WebSocket action vocabulary shared across the platform.

OSS owns the action names. Specific distributions decide which actions are
actually registered on a given app instance.
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
