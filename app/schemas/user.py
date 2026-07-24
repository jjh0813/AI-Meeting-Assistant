from pydantic import BaseModel, Field

from app.models.user import Department, Role


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    display_name: str = Field(min_length=2, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    department: Department
    role: Role
