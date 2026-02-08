from pydantic import BaseModel


class LLMConfigCreate(BaseModel):
    provider: str
    base_url: str
    model: str
    verbose: bool = True


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    verbose: bool | None = None


class LLMConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    verbose: bool

    class Config:
        from_attributes = True
