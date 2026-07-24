from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import Status, User
from app.schemas.user import UserCreate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup")
def signup(body: UserCreate, db: Session = Depends(get_db)):
    username = body.username.strip()
    display_name = body.display_name.strip()
    if not username or not display_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="아이디와 이름을 입력해 주세요.",
        )
    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 사용 중인 아이디입니다.",
        )
    user = User(
        username=username,
        display_name=display_name,
        hashed_password=hash_password(body.password),
        department=body.department,
        role=body.role,
        status=Status.pending,
    )
    db.add(user)
    db.commit()
    return {
        "username": user.username,
        "display_name": user.display_name,
        "status": user.status.value,
    }


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
    token = create_access_token(
        {"sub": user.username, "department": user.department.value, "role": user.role.value}
    )
    return {"access_token": token, "token_type": "bearer"}
