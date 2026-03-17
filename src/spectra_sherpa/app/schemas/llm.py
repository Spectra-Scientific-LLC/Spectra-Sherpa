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


class LLMChatResponse(BaseModel):
    conversation_id: str
    response: str


class LLMConversation(BaseModel):
    conversation_id: str
    messages: List[LLMMessage]
