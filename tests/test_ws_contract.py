from __future__ import annotations

import re
from pathlib import Path

from spectra_sherpa.app.contracts import SHERPA_DATA_STORY as EXPORTED_SHERPA_DATA_STORY
from spectra_sherpa.app.contracts import SHERPA_WRITE_REPORT as EXPORTED_SHERPA_WRITE_REPORT
from spectra_sherpa.app.contracts.capabilities import (
    SHERPA_DATA_STORY as CAPABILITY_SHERPA_DATA_STORY,
)
from spectra_sherpa.app.contracts.capabilities import (
    SHERPA_WRITE_REPORT as CAPABILITY_SHERPA_WRITE_REPORT,
)
from spectra_sherpa.app.ws_actions import (
    SHERPA_CHAT,
    SHERPA_CHAT_WITH_TOOLS,
    SHERPA_DATA_STORY,
    SHERPA_DECIDE,
    SHERPA_GENERATE_CODE,
    SHERPA_IDENTIFY_PEAKS,
    SHERPA_SYNC,
    SHERPA_WRITE_REPORT,
    SHERPA_WS_ACTIONS,
)
from spectra_sherpa.app.ws_events import (
    SHERPA_CHAT_CHUNK,
    SHERPA_CHAT_DONE,
    SHERPA_CHAT_FOLLOW_UPS,
    SHERPA_CHAT_START,
    SHERPA_CODE_ERROR,
    SHERPA_CODE_RESULT,
    SHERPA_DATA_STORY_CHUNK,
    SHERPA_DATA_STORY_ERROR,
    SHERPA_DATA_STORY_RESULT,
    SHERPA_DECISION_ACK,
    SHERPA_ERROR,
    SHERPA_PEAKS_ERROR,
    SHERPA_PEAKS_RESULT,
    SHERPA_RECOMMENDATIONS,
    SHERPA_REPORT_ERROR,
    SHERPA_REPORT_RESULT,
    SHERPA_STATUS,
    SHERPA_SUBSCRIPTION_REQUIRED,
    SHERPA_TOOL_RESULT,
    SHERPA_TOOL_START,
    SHERPA_WORKFLOW_PROPOSED,
    SHERPA_WS_EVENTS,
)


def _extract_ts_object(source: str, const_name: str) -> dict[str, str]:
    pattern = rf"export const {const_name} = \{{(.*?)\}} as const;"
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"Could not find {const_name} in frontend Sherpa WS contract file")

    body = match.group(1)
    entries = re.findall(r"(\w+):\s*\"([^\"]+)\"", body)
    return dict(entries)


def test_frontend_sherpa_ws_contract_matches_backend_constants():
    contract_path = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "sherpaWs.ts"
    source = contract_path.read_text()

    frontend_actions = _extract_ts_object(source, "SHERPA_WS_ACTION")
    frontend_events = _extract_ts_object(source, "SHERPA_WS_EVENT")

    assert frontend_actions == {
        "sync": SHERPA_SYNC,
        "decide": SHERPA_DECIDE,
        "chat": SHERPA_CHAT,
        "identifyPeaks": SHERPA_IDENTIFY_PEAKS,
        "generateCode": SHERPA_GENERATE_CODE,
        "chatWithTools": SHERPA_CHAT_WITH_TOOLS,
        "writeReport": SHERPA_WRITE_REPORT,
        "dataStory": SHERPA_DATA_STORY,
    }
    assert set(frontend_actions.values()) == set(SHERPA_WS_ACTIONS)

    assert frontend_events == {
        "recommendations": SHERPA_RECOMMENDATIONS,
        "decisionAck": SHERPA_DECISION_ACK,
        "chatStart": SHERPA_CHAT_START,
        "chatChunk": SHERPA_CHAT_CHUNK,
        "chatFollowUps": SHERPA_CHAT_FOLLOW_UPS,
        "chatDone": SHERPA_CHAT_DONE,
        "status": SHERPA_STATUS,
        "peaksResult": SHERPA_PEAKS_RESULT,
        "peaksError": SHERPA_PEAKS_ERROR,
        "codeResult": SHERPA_CODE_RESULT,
        "codeError": SHERPA_CODE_ERROR,
        "toolStart": SHERPA_TOOL_START,
        "toolResult": SHERPA_TOOL_RESULT,
        "workflowProposed": SHERPA_WORKFLOW_PROPOSED,
        "subscriptionRequired": SHERPA_SUBSCRIPTION_REQUIRED,
        "error": SHERPA_ERROR,
        "reportResult": SHERPA_REPORT_RESULT,
        "reportError": SHERPA_REPORT_ERROR,
        "dataStoryChunk": SHERPA_DATA_STORY_CHUNK,
        "dataStoryResult": SHERPA_DATA_STORY_RESULT,
        "dataStoryError": SHERPA_DATA_STORY_ERROR,
    }
    assert set(frontend_events.values()) == set(SHERPA_WS_EVENTS)


def test_contract_exports_do_not_shadow_capability_names():
    assert EXPORTED_SHERPA_DATA_STORY == CAPABILITY_SHERPA_DATA_STORY
    assert EXPORTED_SHERPA_WRITE_REPORT == CAPABILITY_SHERPA_WRITE_REPORT
