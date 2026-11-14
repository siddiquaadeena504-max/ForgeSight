from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import (audit, clear_failures, create_token, current_user, hash_password, is_locked, note_failure, require_role, verify_password)

router = APIRouter(tags=["auth"])
ROLES = ("viewer", "inspector", "engineer", "admin")


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=10, max_length=200)
    role: str = Field(pattern="^(viewer|inspector|engineer|admin)$")


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=10, max_length=200)
    role: str | None = Field(default=None, pattern="^(viewer|inspector|engineer|admin)$")
    is_active: bool | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active, "created_at": u.created_at.isoformat()}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if is_locked(email):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        note_failure(email)
        audit(db, None, "auth.login_failed", "user", email, request=request)
        db.commit()
        raise HTTPException(401, "Incorrect email or password")
    clear_failures(email)
    audit(db, user, "auth.login", "user", user.id, request=request)
    db.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "user": user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/auth/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    audit(db, user, "auth.password_changed", "user", user.id, request=request)
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(_: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email already exists")
    u = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.flush()
    audit(db, admin, "user.created", "user", u.id, {"email": email, "role": body.role}, request)
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, admin: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_none=True)
    if u.id == admin.id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise HTTPException(400, "You cannot deactivate or demote your own account")
    if "password" in changes:
        u.password_hash = hash_password(changes.pop("password"))
        changes["password"] = "(changed)"
    for k in ("full_name", "role", "is_active"):
        if k in changes:
            setattr(u, k, changes[k])
    audit(db, admin, "user.updated", "user", u.id, changes, request)
    db.commit()
    return user_out(u)
