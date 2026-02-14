from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    use_tools: bool = Field(
        default=False,
        description="Enable MCP tool-calling loop (requires agenticWorkflow feature flag)",
    )


class LLMChatResponse(BaseModel):
    conversation_id: str
    response: str
    tool_calls: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Tool invocations made during the chat (when use_tools was enabled)",
    )


class LLMConversation(BaseModel):
    conversation_id: str
    messages: List[LLMMessage]


class LLMSuggestNameRequest(BaseModel):
    components: List[str] = Field(default_factory=list)


class LLMPeakIdentifyRequest(BaseModel):
    wavenumbers: List[float]
    absorbance: List[float]


class LLMGenerateCodeRequest(BaseModel):
    task_description: str = Field(..., min_length=1)


class LLMWriteReportRequest(BaseModel):
    experiment: Dict[str, Any] = Field(default_factory=dict)


class LLMDataStoryRequest(BaseModel):
    dataset_info: Dict[str, Any] = Field(..., description="Dataset metadata for narrative generation")


class LLMTextResponse(BaseModel):
    response: str


class LLMNameResponse(BaseModel):
    name: str
