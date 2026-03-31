from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    username: str | None = None
    is_active: bool = True


class UserCreate(UserBase):
    username: str


class UserUpdate(UserBase):
    pass


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserInDBBase(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None


class User(UserInDBBase):
    pass


class UserInDB(UserInDBBase):
    pass
