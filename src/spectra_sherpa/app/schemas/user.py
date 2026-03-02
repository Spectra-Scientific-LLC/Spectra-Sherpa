from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# Shared properties
class UserBase(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    is_superuser: bool = False
    is_active: bool = True


# Properties to receive via API on creation
class UserCreate(UserBase):
    username: str
    password: str


# Properties to receive via API on update
class UserUpdate(UserBase):
    password: Optional[str] = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserInDBBase(UserBase):
    id: Optional[int] = None
    last_login_at: Optional[datetime] = None
    login_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Additional properties to return via API
class User(UserInDBBase):
    pass


# Additional properties stored in DB
class UserInDB(UserInDBBase):
    password_hash: str
