"""Administration commands.

    python -m app.cli create-admin              # prompts for username / password (no hard-coded admin exists)
    python -m app.cli reset-password USERNAME
    python -m app.cli list-users
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.base import SessionLocal
from app.models import Role, User
from app.schemas.auth import USERNAME_RE


def _ask_password(min_len: int) -> str:
    while True:
        p1 = getpass.getpass("Password: ")
        if len(p1) < min_len:
            print(f"Password must be at least {min_len} characters.")
            continue
        if p1 != getpass.getpass("Repeat password: "):
            print("Passwords do not match.")
            continue
        return p1


def create_admin(username: str | None, email: str | None, password: str | None) -> int:
    s = get_settings()
    username = username or input("Admin username: ").strip()
    if not USERNAME_RE.match(username):
        print("Username must be 3-64 chars: letters, digits, '_', '.', '-'", file=sys.stderr)
        return 2
    if password is not None and len(password) < s.min_password_length:
        print(f"Password must be at least {s.min_password_length} characters.", file=sys.stderr)
        return 2
    password = password or _ask_password(s.min_password_length)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(func.lower(User.username) == username.lower())):
            print(f"User '{username}' already exists.", file=sys.stderr)
            return 1
        db.add(User(username=username, email=email or None, role=Role.admin, password_hash=hash_password(password)))
        db.commit()
    print(f"Administrator '{username}' created.")
    return 0


def reset_password(username: str) -> int:
    s = get_settings()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
        if user is None:
            print("No such user.", file=sys.stderr)
            return 1
        user.password_hash = hash_password(_ask_password(s.min_password_length))
        user.token_version += 1      # sign out everywhere
        db.commit()
    print("Password updated; existing sessions were revoked.")
    return 0


def list_users() -> int:
    with SessionLocal() as db:
        for u in db.scalars(select(User).order_by(User.id)):
            print(f"{u.id:>3}  {u.username:<24} {u.role.value:<9} {'active' if u.is_active else 'disabled'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin")
    c.add_argument("--username")
    c.add_argument("--email")
    c.add_argument("--password", help="Avoid on shared machines (visible in shell history); omit to be prompted")
    r = sub.add_parser("reset-password")
    r.add_argument("username")
    sub.add_parser("list-users")
    a = ap.parse_args(argv)
    if a.cmd == "create-admin":
        return create_admin(a.username, a.email, a.password)
    if a.cmd == "reset-password":
        return reset_password(a.username)
    return list_users()


if __name__ == "__main__":
    raise SystemExit(main())
