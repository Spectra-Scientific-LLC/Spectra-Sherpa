"""
Sherpa Engine — server-side Anthropic Claude integration for AI-guided spectral analysis.

This service runs on the server (demo/hybrid mode) and provides intelligent
workflow analysis and advisory chat using Anthropic Claude with MCP tool access.

Architecture:
    Local hybrid client → WS → sherpa_advisor.py → HTTP → server → SherpaEngine → Claude
    Demo browser client → WS → ws_handlers.py → SherpaEngine → Claude (direct)

The engine auto-injects workflow context into the system prompt and makes MCP
tools available (e.g. suggest_preprocessing, describe_node, validate_workflow)
so Claude can provide domain-specific, actionable recommendations.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import settings
from app.schemas.sherpa import WorkflowStateSync

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
MAX_TOKENS = 4096

# ── System Prompt ────────────────────────────────────────────────────

SHERPA_SYSTEM_PROMPT = """\
You are **Sherpa**, an expert spectral analysis advisor for the SpectraSherpa platform.

## Your Expertise
- Vibrational spectroscopy: IR (mid-IR, far-IR), NIR, Raman, UV-Vis
- Chemometrics: PCA, PLS, PCR, MCR-ALS, classification (LDA, PLS-DA, SVM)
- Preprocessing pipelines: baseline correction (ALS, rubberband, SNIP), normalization \
(SNV, MSC, min-max), smoothing (Savitzky-Golay), derivatives, spectral trimming
- Data quality: outlier detection, spectral diagnostics, signal-to-noise assessment
- Workflow design: optimal node ordering, parameter tuning, validation strategies

## Your Role
1. **Analyze** the user's current workflow (nodes, parameters, data shape) and identify \
issues or improvements.
2. **Recommend** concrete preprocessing steps, parameter changes, or modeling approaches.
3. **Use tools** to look up node types, validate workflows, and suggest pipelines — \
do not guess node names or parameters.
4. **Explain** your reasoning clearly, referencing spectroscopic principles.
5. **Ask** clarifying questions when the spectral technique or analysis goal is unclear.

## Guidelines
- Always use `list_node_types` or `describe_node` to verify node types and parameters \
before recommending them.
- When suggesting a preprocessing pipeline, use `suggest_preprocessing` to get a \
baseline recommendation, then refine based on the specific workflow context.
- Use `validate_workflow` to check structural issues before suggesting fixes.
- Keep responses focused and actionable — bullet points over paragraphs.
- If you don't know something, say so rather than inventing scientific facts.
- Reference spectral regions in cm⁻¹ (IR/Raman) or nm (UV-Vis/NIR) as appropriate.
"""


def _build_workflow_context(sync: WorkflowStateSync) -> str:
    """Format workflow state as context for the system prompt."""
    parts = ["## Current Workflow Context"]

    if sync.workflow_name:
        parts.append(f"**Workflow:** {sync.workflow_name}")
    if sync.spectral_technique:
        parts.append(f"**Technique:** {sync.spectral_technique}")
    if sync.n_samples is not None or sync.n_features is not None:
        parts.append(f"**Data shape:** {sync.n_samples or '?'} samples × {sync.n_features or '?'} features")

    if sync.nodes:
        parts.append("\n### Nodes")
        for node in sync.nodes:
            label = node.label or node.node_type
            params_str = ""
            if node.parameters:
                params_str = f" — params: {json.dumps(node.parameters, default=str)}"
            shape_str = ""
            if node.result_shape:
                shape_str = f" [{' × '.join(str(s) for s in node.result_shape)}]"
            parts.append(f"- `{node.node_id}` **{node.node_type}** ({label}){shape_str}{params_str}")

    if sync.edges:
        parts.append("\n### Connections")
        for edge in sync.edges:
            parts.append(f"- {edge.from_node_id} → {edge.to_node_id}")

    return "\n".join(parts)


# ── Engine ───────────────────────────────────────────────────────────

class SherpaEngine:
    """Direct Anthropic Claude integration for Sherpa Advisor.

    Requires ``SHERPA_ENGINE_API_KEY`` to be set in the environment.
    """

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def is_available(self) -> bool:
        if not settings.sherpa_engine_api_key:
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            logger.warning(
                "SHERPA_ENGINE_API_KEY is set but the 'anthropic' package is not installed. "
                "Sherpa Engine will be DISABLED. Install it with: pip install anthropic"
            )
            return False

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    "The 'anthropic' package is required for SherpaEngine. "
                    "Install it with: pip install anthropic"
                )
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.sherpa_engine_api_key,
            )
        return self._client

    def _get_tools(self) -> list[dict[str, Any]]:
        """Get MCP tool definitions in Anthropic format."""
        from app.services.tools import tool_registry
        return tool_registry.to_anthropic_tools()

    async def _execute_tool(
        self, name: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an MCP tool and return the result."""
        from app.services.tools.executor import ToolExecutionContext, execute_tool
        from app.services.tools.schemas import ToolInvocation

        invocation = ToolInvocation(tool_name=name, arguments=arguments)
        ctx = ToolExecutionContext(session=None, user=None)
        result = await execute_tool(invocation, ctx, allow_internal=True)
        return {
            "success": result.success,
            "result": result.result,
            "error": result.error,
        }

    # ── Core API ──────────────────────────────────────────────

    async def analyze_workflow(
        self, sync: WorkflowStateSync,
    ) -> AsyncIterator[str]:
        """Analyze a workflow and stream recommendations.

        This is the main entry point for ``sherpa_sync``. Builds a context-rich
        prompt, calls Claude with MCP tools, and yields text chunks.
        """
        workflow_context = _build_workflow_context(sync)
        system = f"{SHERPA_SYSTEM_PROMPT}\n\n{workflow_context}"

        user_message = (
            "Analyze my current workflow and provide specific recommendations. "
            "Consider the preprocessing pipeline, parameter choices, data shape, "
            "and spectral technique. Use available tools to verify node types "
            "and suggest improvements."
        )

        async for chunk in self._stream_with_tools(system, user_message):
            yield chunk

    async def chat(
        self,
        message: str,
        workflow_context: WorkflowStateSync | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        """Stream a follow-up chat response with workflow context.

        This is the entry point for ``sherpa_chat``. Maintains conversation
        context and provides tool access.
        """
        system = SHERPA_SYSTEM_PROMPT
        if workflow_context:
            system = f"{SHERPA_SYSTEM_PROMPT}\n\n{_build_workflow_context(workflow_context)}"

        async for chunk in self._stream_with_tools(
            system, message, history=history,
        ):
            yield chunk

    # ── Internal streaming + tool loop ────────────────────────

    async def _stream_with_tools(
        self,
        system: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        """Multi-turn tool-calling loop with streaming final response.

        Flow:
        1. Call Claude with tools (non-streaming) to check for tool calls
        2. If tool calls: execute them, append results, loop (up to MAX_TOOL_ROUNDS)
        3. Once Claude returns text without tool calls: stream the final response
        """
        client = self._get_client()
        model = settings.sherpa_engine_model
        tools = self._get_tools()

        # Build message history
        messages: list[dict[str, Any]] = []
        if history:
            for msg in history[-10:]:  # Last 10 messages for context
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        # Tool-calling rounds (non-streaming)
        for round_num in range(MAX_TOOL_ROUNDS):
            logger.info("Sherpa tool round %d/%d", round_num + 1, MAX_TOOL_ROUNDS)

            response = await client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=messages,
                tools=tools if tools else [],
            )

            # Check for tool_use blocks
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if not tool_use_blocks:
                # No tool calls — yield text and we're done
                for block in text_blocks:
                    yield block.text
                return

            # Yield any intermediate text before tool calls
            for block in text_blocks:
                if block.text.strip():
                    yield block.text

            # Execute tool calls
            # First, append the assistant's response (with tool_use blocks)
            messages.append({
                "role": "assistant",
                "content": [
                    {"type": b.type, **({"text": b.text} if b.type == "text" else {"id": b.id, "name": b.name, "input": b.input})}
                    for b in response.content
                ],
            })

            # Yield progress indicator so the frontend shows activity
            tool_names = [b.name for b in tool_use_blocks]
            yield f"\n\n*Using tools: {', '.join(tool_names)}…*\n\n"

            # Execute each tool and build tool_result blocks
            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                logger.info("Sherpa calling tool: %s(%s)", block.name, json.dumps(block.input)[:200])
                result = await self._execute_tool(block.name, block.input)
                result_text = json.dumps(result["result"] if result["success"] else {"error": result["error"]}, default=str)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
                logger.info("Sherpa tool %s → %s", block.name, "success" if result["success"] else f"error: {result['error']}")

            messages.append({"role": "user", "content": tool_results})

        # If we exhausted all rounds, do one final streaming call without tools
        logger.warning("Sherpa exhausted %d tool rounds, final call without tools", MAX_TOOL_ROUNDS)
        async with client.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


# ── Singleton ────────────────────────────────────────────────────────

_engine_instance: SherpaEngine | None = None


def get_sherpa_engine() -> SherpaEngine:
    """Get the singleton SherpaEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SherpaEngine()
    return _engine_instance


async def close_sherpa_engine() -> None:
    """Close the singleton engine (call on app shutdown)."""
    global _engine_instance
    if _engine_instance:
        await _engine_instance.close()
        _engine_instance = None
