from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import Department, Role, Status, User

USERS = [
    ("acc_user", "김철수", Department.accounting, Role.member),
    ("acc_kim", "김민지", Department.accounting, Role.member),
    ("acc_admin", "회계관리자", Department.accounting, Role.admin),
    ("sales_admin", "영업관리자", Department.sales, Role.admin),
    ("sales_park", "박영희", Department.sales, Role.member),
    ("mgmt_choi", "최민수", Department.management, Role.member),
    ("mgmt_admin", "경영관리자", Department.management, Role.admin),
]


def seed():
    db = SessionLocal()
    created = 0
    for username, display_name, department, role in USERS:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            if not existing.display_name or existing.display_name == existing.username:
                existing.display_name = display_name
            continue
        db.add(
            User(
                username=username,
                display_name=display_name,
                hashed_password=hash_password("pass1234"),
                department=department,
                role=role,
                status=Status.approved,
            )
        )
        created += 1
    db.commit()
    db.close()
    print(f"created {created} new users")


if __name__ == "__main__":
    seed()
