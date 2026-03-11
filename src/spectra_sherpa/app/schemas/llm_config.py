from pydantic import BaseModel, ConfigDict


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
    model_config = ConfigDict(from_attributes=True)

    provider: str
    base_url: str
    model: str
    verbose: bool
