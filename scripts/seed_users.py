from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import Department, Role, User

USERS = [
    ("acc_user", Department.accounting, Role.member),
    ("acc_kim", Department.accounting, Role.member),
    ("acc_admin", Department.accounting, Role.admin),
    ("sales_admin", Department.sales, Role.admin),
    ("sales_park", Department.sales, Role.member),
    ("mgmt_choi", Department.management, Role.member),
    ("mgmt_admin", Department.management, Role.admin),
]


def seed():
    db = SessionLocal()
    created = 0
    for username, department, role in USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        db.add(
            User(
                username=username,
                hashed_password=hash_password("pass1234"),
                department=department,
                role=role,
            )
        )
        created += 1
    db.commit()
    db.close()
    print(f"created {created} new users")


if __name__ == "__main__":
    seed()
