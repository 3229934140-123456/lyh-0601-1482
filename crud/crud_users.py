from typing import List, Optional
from sqlalchemy.orm import Session

from models import User, UserRole
from schemas import UserCreate


def create_user(db: Session, user: UserCreate) -> User:
    db_user = User(
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_user(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def get_users(
    db: Session,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[User]:
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    return query.order_by(User.id.asc()).offset(skip).limit(limit).all()


def count_users(
    db: Session,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
) -> int:
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    return query.count()


def update_user_role(db: Session, user_id: int, role: UserRole) -> Optional[User]:
    user = get_user(db, user_id)
    if not user:
        return None
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def toggle_user_active(db: Session, user_id: int) -> Optional[User]:
    user = get_user(db, user_id)
    if not user:
        return None
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = get_user(db, user_id)
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True
