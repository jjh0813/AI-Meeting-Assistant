from pydantic import BaseModel

from app.models.user import Department, Role


class UserCreate(BaseModel):
    username: str
    password: str
    department: Department
    role: Role
