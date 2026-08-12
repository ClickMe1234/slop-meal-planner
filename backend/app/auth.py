from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import DomainError
from .models import User, UserRole, UserSession

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except VerifyMismatchError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, *, remember_me: bool = True) -> tuple[str, str]:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(raw_token),
            csrf_hash=token_hash(csrf),
            remember_me=remember_me,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_days),
        )
    )
    db.flush()
    return raw_token, csrf


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: UserSession
    token: str


def get_auth_context(
    request: Request,
    mp_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not mp_session:
        raise DomainError("AUTHENTICATION_REQUIRED", "Please sign in", 401)
    user_session = db.scalar(
        select(UserSession).where(UserSession.token_hash == token_hash(mp_session))
    )
    if user_session is None:
        raise DomainError("INVALID_SESSION", "The session is invalid", 401)
    expiry = user_session.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        db.delete(user_session)
        db.commit()
        raise DomainError("SESSION_EXPIRED", "The session has expired", 401)
    user = db.get(User, user_session.user_id)
    if user is None or not user.active:
        raise DomainError("ACCOUNT_DISABLED", "The account is disabled", 403)
    if user.must_change_password and request.url.path not in {
        "/api/v1/auth/me",
        "/api/v1/auth/csrf",
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
    }:
        raise DomainError(
            "PASSWORD_CHANGE_REQUIRED",
            "Change the temporary password before using the household",
            403,
        )
    return AuthContext(user=user, session=user_session, token=mp_session)


def require_csrf(
    context: AuthContext = Depends(get_auth_context),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthContext:
    if not csrf_token or not secrets.compare_digest(
        token_hash(csrf_token), context.session.csrf_hash
    ):
        raise DomainError("CSRF_FAILED", "The CSRF token is missing or invalid", 403)
    return context


def require_owner(context: AuthContext = Depends(require_csrf)) -> AuthContext:
    if context.user.role != UserRole.OWNER.value:
        raise DomainError("OWNER_REQUIRED", "This action requires the owner role", 403)
    return context
