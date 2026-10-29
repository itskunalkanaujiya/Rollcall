from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import COOKIE_NAME, client_ip, current_user, require_admin
from app.core.errors import AppError
from app.core.rate_limit import limiter
from app.core.security import DUMMY_HASH, create_access_token, hash_password, verify_password
from app.core.timeutil import utc_now
from app.database.base import get_db
from app.models import Role, User
from app.schemas.auth import LoginRequest, UserCreate, UserOut, UserUpdate
from app.services import audit_service

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ip = client_ip(request) or "?"
    key = f"login:{ip}:{body.username.lower()}"
    allowed, retry = limiter.check(key, s.login_rate_limit, s.login_rate_window_seconds)
    if not allowed:
        raise AppError(429, "rate_limited", f"Too many login attempts. Try again in {retry}s.")
    user = db.scalar(select(User).where(
        (func.lower(User.username) == body.username.lower()) | (func.lower(User.email) == body.username.lower())))
    # Always run one bcrypt verification so timing does not reveal whether the account exists.
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit_service.log(db, "login_failed", None, "user", None, {"username": body.username[:64]}, ip)
        raise AppError(401, "invalid_credentials", "Invalid username or password")
    limiter.reset(key)
    token, expires = create_access_token(user.id, user.token_version)
    user.last_login_at = utc_now()
    db.commit()
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=s.cookie_secure, samesite=s.cookie_samesite,
                        max_age=s.access_token_minutes * 60, path="/")
    audit_service.log(db, "login", user, "user", user.id, None, ip)
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version += 1          # invalidates every token issued to this user
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    audit_service.log(db, "logout", user, "user", user.id, None, client_ip(request))
    response.status_code = 204


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


# ---- user administration (admin only) ---------------------------------------
@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.username)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = get_settings()
    if len(body.password) < s.min_password_length:
        raise AppError(422, "weak_password", f"Password must be at least {s.min_password_length} characters")
    user = User(username=body.username, email=body.email, role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "duplicate_user", "Username or email already exists") from None
    audit_service.log(db, "user_create", admin, "user", user.id, {"role": user.role.value}, client_ip(request))
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "not_found", "User not found")
    s = get_settings()
    changes: dict = {}
    if body.role is not None and body.role != user.role:
        if user.id == admin.id:
            raise AppError(400, "self_demotion", "You cannot change your own role")
        user.role = body.role
        changes["role"] = body.role.value
    if body.is_active is not None and body.is_active != user.is_active:
        if user.id == admin.id:
            raise AppError(400, "self_disable", "You cannot disable your own account")
        user.is_active = body.is_active
        changes["is_active"] = body.is_active
    if body.password:
        if len(body.password) < s.min_password_length:
            raise AppError(422, "weak_password", f"Password must be at least {s.min_password_length} characters")
        user.password_hash = hash_password(body.password)
        user.token_version += 1
        changes["password"] = "changed"
    if user.role != Role.admin or not user.is_active:
        remaining = db.scalar(select(func.count(User.id)).where(
            User.role == Role.admin, User.is_active.is_(True), User.id != user.id))
        if not remaining and (changes.get("role") or changes.get("is_active") is False):
            db.rollback()
            raise AppError(400, "last_admin", "At least one active administrator is required")
    db.commit()
    audit_service.log(db, "user_update", admin, "user", user.id, changes, client_ip(request))
    return user
