"""Resolution and first-linking rules for external authentication identities."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import DomainError
from ..models import ExternalIdentity, User

logger = logging.getLogger(__name__)


def normalize_issuer(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise DomainError("AUTHENTIK_PROVIDER_INVALID", "The Authentik issuer is missing", 503)
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise DomainError("AUTHENTIK_PROVIDER_INVALID", "The Authentik issuer is invalid", 503) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DomainError("AUTHENTIK_PROVIDER_INVALID", "The Authentik issuer is invalid", 503)
    if any(character in candidate for character in "\x00\r\n"):
        raise DomainError("AUTHENTIK_PROVIDER_INVALID", "The Authentik issuer is invalid", 503)
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_subject(value: str) -> str:
    subject = value.strip()
    if not subject or len(subject) > 512 or any(
        character in subject for character in "\x00\r\n"
    ):
        raise DomainError("AUTHENTIK_IDENTITY_INVALID", "The external identity is invalid", 403)
    return subject


def normalize_claimed_username(value: str) -> str:
    username = value.strip()
    if not username or len(username) > 80 or any(
        character in username for character in "\x00\r\n"
    ):
        raise DomainError(
            "AUTHENTIK_USERNAME_REQUIRED",
            "Authentik did not provide a usable username for this account",
            403,
        )
    return username


def _matching_users(db: Session, username: str) -> list[User]:
    folded = username.casefold()
    return [
        user
        for user in db.scalars(select(User)).all()
        if user.username.strip().casefold() == folded
    ]


def resolve_external_identity(
    db: Session,
    *,
    auth_method: str,
    issuer: str,
    subject: str,
    claimed_username: str,
) -> User:
    """Resolve a stable subject, or link it to one existing Slop account.

    The caller owns the surrounding transaction and must commit after creating
    the local session. This lets proxy and OIDC callbacks link the identity and
    session atomically.
    """

    normalized_issuer = normalize_issuer(issuer)
    normalized_subject = normalize_subject(subject)
    normalized_username = normalize_claimed_username(claimed_username)
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.auth_method == auth_method,
            ExternalIdentity.issuer == normalized_issuer,
            ExternalIdentity.subject == normalized_subject,
        )
    )
    now = datetime.now(timezone.utc)
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is None:
            raise DomainError(
                "AUTHENTIK_IDENTITY_CONFLICT",
                "The external identity no longer has a local account",
                409,
            )
        if not user.active:
            raise DomainError(
                "AUTHENTIK_ACCOUNT_DISABLED",
                "This Slop account is inactive; ask the household owner to reactivate it",
                403,
            )
        identity.last_seen_username = normalized_username
        identity.last_seen_at = now
        return user

    if (db.scalar(select(User.id).limit(1)) is None):
        raise DomainError(
            "AUTHENTIK_ACCOUNT_SETUP_REQUIRED",
            "No Slop account exists yet. Temporarily enable builtin mode to create the owner account.",
            409,
        )

    matches = _matching_users(db, normalized_username)
    if not matches:
        raise DomainError(
            "AUTHENTIK_UNKNOWN_ACCOUNT",
            "No active Slop account matches this Authentik username. Ask the owner to prepare the account in builtin mode.",
            403,
        )
    if len(matches) != 1:
        raise DomainError(
            "AUTHENTIK_AMBIGUOUS_ACCOUNT",
            "More than one active Slop account matches this Authentik username",
            403,
        )
    user = matches[0]
    if not user.active:
        raise DomainError(
            "AUTHENTIK_ACCOUNT_DISABLED",
            "This Slop account is inactive; ask the household owner to reactivate it",
            403,
        )
    existing_for_user = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.user_id == user.id,
            ExternalIdentity.auth_method == auth_method,
            ExternalIdentity.issuer == normalized_issuer,
        )
    )
    if existing_for_user is not None:
        raise DomainError(
            "AUTHENTIK_IDENTITY_CONFLICT",
            "This Slop account is already linked to a different Authentik identity",
            409,
        )

    identity = ExternalIdentity(
        user_id=user.id,
        auth_method=auth_method,
        issuer=normalized_issuer,
        subject=normalized_subject,
        username_at_link=normalized_username,
        last_seen_username=normalized_username,
        created_at=now,
        last_seen_at=now,
    )
    db.add(identity)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent first login may have won either uniqueness race. Read
        # the committed winner and use it only if it points at this same user;
        # never silently re-link a competing subject.
        db.rollback()
        winner = db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.auth_method == auth_method,
                ExternalIdentity.issuer == normalized_issuer,
                ExternalIdentity.subject == normalized_subject,
            )
        )
        if winner is not None:
            winner_user = db.get(User, winner.user_id)
            if winner_user is not None and winner_user.active:
                winner.last_seen_username = normalized_username
                winner.last_seen_at = datetime.now(timezone.utc)
                return winner_user
        raise DomainError(
            "AUTHENTIK_IDENTITY_CONFLICT",
            "The external identity could not be linked safely; try again",
            409,
        ) from None
    logger.info(
        "external identity linked",
        extra={"auth_mode": auth_method, "user_id": user.id},
    )
    return user


def identity_for_subject(
    db: Session, *, auth_method: str, issuer: str, subject: str
) -> ExternalIdentity | None:
    return db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.auth_method == auth_method,
            ExternalIdentity.issuer == normalize_issuer(issuer),
            ExternalIdentity.subject == normalize_subject(subject),
        )
    )
