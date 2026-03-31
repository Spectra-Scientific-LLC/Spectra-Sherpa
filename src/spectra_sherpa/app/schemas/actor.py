from pydantic import BaseModel, ConfigDict


class Actor(BaseModel):
    """Minimal actor payload exposed by OSS compatibility endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool = True
