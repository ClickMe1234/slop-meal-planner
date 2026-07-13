from datetime import datetime, timezone
import secrets

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import (
    AuthContext,
    create_session,
    get_auth_context,
    hash_password,
    require_csrf,
    require_owner,
    token_hash,
    verify_password,
)
from ..config import get_settings
from ..db import get_db
from ..errors import DomainError
from ..models import Household, HouseholdMember, User, UserRole, UserSession
from ..schemas import (
    AuthOut,
    CollaboratorCreate,
    LoginRequest,
    PasswordChange,
    SetupRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        "mp_session",
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/",
    )


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)) -> dict[str, bool]:
    return {"setup_required": (db.scalar(select(func.count(User.id))) or 0) == 0}


@router.post("/setup", response_model=AuthOut, status_code=201)
def setup(payload: SetupRequest, response: Response, db: Session = Depends(get_db)):
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        raise DomainError("ALREADY_CONFIGURED", "The owner account already exists", 409)
    if payload.setup_token != get_settings().setup_token:
        raise DomainError("INVALID_SETUP_TOKEN", "The setup token is invalid", 403)
    household = Household(name=payload.household_name, timezone=get_settings().timezone)
    db.add(household)
    db.flush()
    member = HouseholdMember(household_id=household.id, name=payload.username)
    db.add(member)
    db.flush()
    user = User(
        household_id=household.id,
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        role=UserRole.OWNER.value,
        member_id=member.id,
    )
    db.add(user)
    db.flush()
    raw_token, csrf = create_session(db, user)
    db.commit()
    _set_session_cookie(response, raw_token)
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/login", response_model=AuthOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.username) == username))
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise DomainError("INVALID_CREDENTIALS", "Username or password is incorrect", 401)
    raw_token, csrf = create_session(db, user)
    db.commit()
    _set_session_cookie(response, raw_token)
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    db.delete(context.session)
    db.commit()
    response.delete_cookie("mp_session", path="/")


@router.get("/me", response_model=UserOut)
def me(context: AuthContext = Depends(get_auth_context)):
    return context.user


@router.get("/csrf")
def refresh_csrf(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    """Rotate a CSRF token after a browser reload while retaining its session."""

    csrf = secrets.token_urlsafe(32)
    context.session.csrf_hash = token_hash(csrf)
    db.commit()
    return {"csrf_token": csrf}


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, context.user.password_hash):
        raise DomainError("INVALID_PASSWORD", "The current password is incorrect", 403)
    context.user.password_hash = hash_password(payload.new_password)
    context.user.must_change_password = False
    context.user.version += 1
    db.commit()


@router.get("/users", response_model=list[UserOut])
def list_users(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    if context.user.role != UserRole.OWNER.value:
        raise DomainError("OWNER_REQUIRED", "This action requires the owner role", 403)
    return db.scalars(select(User).where(User.household_id == context.user.household_id)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_collaborator(
    payload: CollaboratorCreate,
    context: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise DomainError("USERNAME_TAKEN", "That username is already in use", 409)
    if payload.member_id:
        member = db.get(HouseholdMember, payload.member_id)
        if member is None or member.household_id != context.user.household_id:
            raise DomainError("INVALID_MEMBER", "The selected household member is invalid")
    user = User(
        household_id=context.user.household_id,
        username=username,
        password_hash=hash_password(payload.temporary_password),
        role=UserRole.COLLABORATOR.value,
        member_id=payload.member_id,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def disable_user(
    user_id: str,
    context: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None or user.household_id != context.user.household_id:
        raise DomainError("NOT_FOUND", "User was not found", 404)
    if user.id == context.user.id:
        raise DomainError("OWNER_SELF_DISABLE", "The signed-in owner cannot disable themselves")
    user.active = False
    user.version += 1
    sessions = db.scalars(select(UserSession).where(UserSession.user_id == user.id)).all()
    for session in sessions:
        db.delete(session)
    db.commit()
