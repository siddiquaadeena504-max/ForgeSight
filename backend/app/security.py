from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, User

ROLE_RANK = {"viewer": 0, "inspector": 1, "engineer": 2, "admin": 3}
_bearer = HTTPBearer(auto_error=False)
_failed: dict[str, list[float]] = defaultdict(list)
LOCK_WINDOW, LOCK_ATTEMPTS = 300, 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, s.secret_key, algorithm="HS256")


def is_locked(email: str) -> bool:
    now = time.time()
    _failed[email] = [t for t in _failed[email] if now - t < LOCK_WINDOW]
    return len(_failed[email]) >= LOCK_ATTEMPTS


def note_failure(email: str) -> None:
    _failed[email].append(time.time())


def clear_failures(email: str) -> None:
    _failed.pop(email, None)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(cred.credentials, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User disabled or removed")
    return user


def require_role(minimum: str):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{minimum}' or higher")
        return user

    return dep


def audit(db: Session, user: User | None, action: str, entity: str | None = None, entity_id: str | int | None = None,
          detail: dict | None = None, request: Request | None = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, user_email=user.email if user else None, action=action, entity=entity,
                    entity_id=None if entity_id is None else str(entity_id), detail=detail,
                    ip=request.client.host if request and request.client else None))
