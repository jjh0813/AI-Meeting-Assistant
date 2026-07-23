from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_approved_user, get_current_admin, get_current_user
from app.core.database import get_db
from app.models.user import Status, User

router = APIRouter(tags=["users"])


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "department": current_user.department.value,
        "role": current_user.role.value,
        "status": current_user.status.value,
    }


@router.get("/users/same-department")
def list_same_department(
    current_user: User = Depends(get_approved_user), db: Session = Depends(get_db)
):
    users = db.query(User).filter(User.department == current_user.department).all()
    return [
        {"username": u.username, "department": u.department.value, "role": u.role.value}
        for u in users
    ]


@router.get("/users/pending")
def list_pending_users(
    current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
):
    users = (
        db.query(User)
        .filter(User.status == Status.pending, User.department == current_admin.department)
        .all()
    )
    return [
        {
            "id": u.id,
            "username": u.username,
            "department": u.department.value,
            "role": u.role.value,
        }
        for u in users
    ]


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.id == user_id, User.department == current_admin.department)
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.status = Status.approved
    db.commit()
    return {"id": user.id, "username": user.username, "status": user.status.value}


@router.post("/users/{user_id}/reject")
def reject_user(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.id == user_id, User.department == current_admin.department)
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.status = Status.rejected
    db.commit()
    return {"id": user.id, "username": user.username, "status": user.status.value}
