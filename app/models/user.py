import enum

from sqlalchemy import Column, DateTime, Enum, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class Department(str, enum.Enum):
    accounting = "회계"
    management = "경영"
    sales = "영업"


class Role(str, enum.Enum):
    member = "일반"
    admin = "관리자"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    department = Column(Enum(Department), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.member)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
