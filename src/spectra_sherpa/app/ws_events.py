"""Canonical Sherpa WebSocket event vocabulary shared across the platform.

**Source of truth for all WS events.**  Both the frontend (``sherpaWs.ts``)
and the server WS handlers reference these constants.

To add a new event:
1. Define the constant here.
2. Add it to ``SHERPA_WS_EVENTS``.
3. Add the matching key in ``frontend/src/lib/sherpaWs.ts → SHERPA_WS_EVENT``.
4. Handle it in ``frontend/src/stores/sherpa.ts → handleWsMessage()``.
5. Run ``pytest tests/test_ws_contract.py`` — it will fail until all three are in sync.
"""

SHERPA_RECOMMENDATIONS = "sherpa_recommendations"
SHERPA_DECISION_ACK = "sherpa_decision_ack"
SHERPA_CHAT_START = "sherpa_chat_start"
SHERPA_CHAT_CHUNK = "sherpa_chat_chunk"
SHERPA_CHAT_FOLLOW_UPS = "sherpa_chat_follow_ups"
SHERPA_CHAT_DONE = "sherpa_chat_done"
SHERPA_STATUS = "sherpa_status"
SHERPA_PEAKS_RESULT = "sherpa_peaks_result"
SHERPA_PEAKS_ERROR = "sherpa_peaks_error"
SHERPA_CODE_RESULT = "sherpa_code_result"
SHERPA_CODE_ERROR = "sherpa_code_error"
SHERPA_TOOL_START = "sherpa_tool_start"
SHERPA_TOOL_RESULT = "sherpa_tool_result"
SHERPA_WORKFLOW_PROPOSED = "sherpa_workflow_proposed"
SHERPA_SUBSCRIPTION_REQUIRED = "sherpa_subscription_required"
SHERPA_ERROR = "sherpa_error"
SHERPA_REPORT_RESULT = "sherpa_report_result"
SHERPA_REPORT_ERROR = "sherpa_report_error"
SHERPA_DATA_STORY_CHUNK = "sherpa_data_story_chunk"
SHERPA_DATA_STORY_RESULT = "sherpa_data_story_result"
SHERPA_DATA_STORY_ERROR = "sherpa_data_story_error"

SHERPA_WS_EVENTS: tuple[str, ...] = (
    SHERPA_RECOMMENDATIONS,
    SHERPA_DECISION_ACK,
    SHERPA_CHAT_START,
    SHERPA_CHAT_CHUNK,
    SHERPA_CHAT_FOLLOW_UPS,
    SHERPA_CHAT_DONE,
    SHERPA_STATUS,
    SHERPA_PEAKS_RESULT,
    SHERPA_PEAKS_ERROR,
    SHERPA_CODE_RESULT,
    SHERPA_CODE_ERROR,
    SHERPA_TOOL_START,
    SHERPA_TOOL_RESULT,
    SHERPA_WORKFLOW_PROPOSED,
    SHERPA_SUBSCRIPTION_REQUIRED,
    SHERPA_ERROR,
    SHERPA_REPORT_RESULT,
    SHERPA_REPORT_ERROR,
    SHERPA_DATA_STORY_CHUNK,
    SHERPA_DATA_STORY_RESULT,
    SHERPA_DATA_STORY_ERROR,
)
