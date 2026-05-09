"""Canonical feature-flag vocabulary shared across OSS and server repos.

OSS defines the *names*; the server (or subscription overlay) provides
the *values*.  Frontend reads ``config.features[CAPABILITY_NAME]`` as
booleans — the transport shape is unchanged.

Import these constants instead of scattering string literals across
config.py, config routes, and ws_handlers.
"""

# ── Sherpa AI capabilities (server-gated) ──────────────────────────────

SHERPA_ADVISOR = "sherpaAdvisor"
SHERPA_PEAK_ID = "sherpaPeakId"
SHERPA_CODE_GEN = "sherpaCodeGen"
SHERPA_WRITE_REPORT = "sherpaWriteReport"
SHERPA_AGENTIC_TOOLS = "sherpaAgenticTools"
SHERPA_DATA_STORY = "sherpaDataStory"
SHERPA_FULL_CONTEXT = "sherpaFullContext"
SHERPA_GUIDANCE = "sherpaGuidance"

# ── OSS capabilities ───────────────────────────────────────────────────

CHAT_ASSISTANT = "chatAssistant"

# ── All Sherpa capabilities (convenience tuple for demo enablement) ────

ALL_SHERPA_CAPABILITIES: tuple[str, ...] = (
    SHERPA_ADVISOR,
    SHERPA_PEAK_ID,
    SHERPA_CODE_GEN,
    SHERPA_WRITE_REPORT,
    SHERPA_AGENTIC_TOOLS,
    SHERPA_DATA_STORY,
    SHERPA_FULL_CONTEXT,
    SHERPA_GUIDANCE,
)
