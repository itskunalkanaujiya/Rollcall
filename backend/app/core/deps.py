from __future__ import annotations

from typing import Callable

from fastapi import Depends, Request, WebSocket
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.database.base import get_db
from app.models import Role, User

COOKIE_NAME = "access_token"


def _token_from(request_or_ws: Request | WebSocket) -> str | None:
    tok = request_or_ws.cookies.get(COOKIE_NAME)
    if tok:
        return tok
    auth = request_or_ws.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload.get("ver"):
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, _token_from(request))
    if user is None:
        raise AppError(401, "not_authenticated", "Authentication required")
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have permission to perform this action")
        return user
    return dep


require_admin = require_roles(Role.admin)
require_operator = require_roles(Role.admin, Role.operator)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
