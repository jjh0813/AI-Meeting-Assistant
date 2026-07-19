from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter(tags=["users"])


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "department": current_user.department.value,
        "role": current_user.role.value,
    }


@router.get("/users/same-department")
def list_same_department(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    users = (
        db.query(User).filter(User.department == current_user.department).all()
    )
    return [
        {
            "username": u.username,
            "department": u.department.value,
            "role": u.role.value,
        }
        for u in users
    ]