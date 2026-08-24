from datetime import datetime, timedelta, timezone
import hashlib
import logging
from collections import defaultdict, deque
import secrets
import threading
import time

from fastapi import APIRouter, Cookie, Depends, Form, Header, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
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
from ..models import (
    AuthMethod,
    ExternalIdentity,
    Household,
    HouseholdMember,
    OidcLogoutReplay,
    User,
    UserRole,
    UserSession,
)
from ..services.external_identity import normalize_issuer, resolve_external_identity
from ..services.integration_credentials import encrypt_value
from ..services.oidc import (
    OIDC_AUTH_METHOD,
    OIDC_TRANSACTION_COOKIE,
    authorization_url,
    claim_username,
    end_session_url,
    exchange_code,
    fetch_userinfo,
    get_provider_metadata,
    sanitize_return_path,
    transaction_from_cookie,
    validate_callback_state,
    validate_jwt,
    validate_userinfo_subject,
)
from ..schemas import (
    AuthOut,
    CollaboratorCreate,
    LoginRequest,
    PasswordChange,
    SetupRequest,
    UserOut,
    UserPreferencesUpdate,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
_login_lock = threading.Lock()
_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_password_verifiers = threading.BoundedSemaphore(value=4)
_dummy_password_hash = hash_password("not-a-real-account-password-value")


def reset_login_security_state() -> None:
    with _login_lock:
        _login_attempts.clear()


def _rate_limit_login(source: str, username: str) -> None:
    settings = get_settings()
    now = time.monotonic()
    window_start = now - settings.login_rate_window_seconds
    keys = (
        (f"source:{source}", settings.login_rate_limit_per_source),
        (f"account:{username}", settings.login_rate_limit_per_account),
    )
    with _login_lock:
        for key, limit in keys:
            attempts = _login_attempts[key]
            while attempts and attempts[0] < window_start:
                attempts.popleft()
            if len(attempts) >= limit:
                raise DomainError(
                    "LOGIN_RATE_LIMITED",
                    "Too many sign-in attempts. Wait before trying again.",
                    429,
                )
        for key, _ in keys:
            _login_attempts[key].append(now)


def _set_session_cookie(response: Response, token: str, *, persistent: bool = True) -> None:
    settings = get_settings()
    response.set_cookie(
        "mp_session",
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 86400 if persistent else None,
        path="/",
    )


def _renew_persistent_session(response: Response, context: AuthContext, db: Session) -> None:
    if not context.session.remember_me:
        return
    settings = get_settings()
    context.session.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_days)
    db.commit()
    _set_session_cookie(response, context.token)


def _require_builtin_mode() -> None:
    if get_settings().auth_mode != AuthMethod.BUILTIN.value:
        raise DomainError(
            "AUTH_METHOD_DISABLED",
            "Password authentication is disabled while an Authentik mode is active. Temporarily enable builtin mode to use it.",
            409,
        )


def _manual_authenticated_context(
    request: Request,
    mp_session: str | None,
    csrf_token: str | None,
    db: Session,
    *,
    owner: bool = False,
) -> AuthContext:
    context = get_auth_context(request, mp_session, db)
    context = require_csrf(context, csrf_token)
    if owner and context.user.role != UserRole.OWNER.value:
        raise DomainError("OWNER_REQUIRED", "This action requires the owner role", 403)
    return context


def _proxy_headers(request: Request) -> tuple[str, str]:
    settings = get_settings()
    provided_secret = request.headers.get("X-Slop-Auth-Proxy-Secret")
    if not provided_secret or not secrets.compare_digest(
        provided_secret, settings.authentik_proxy_shared_secret
    ):
        raise DomainError(
            "AUTHENTIK_PROXY_SECRET_INVALID",
            "The trusted Authentik proxy proof is missing or invalid",
            401,
        )
    subject = request.headers.get("X-authentik-uid")
    username = request.headers.get("X-authentik-username")
    app_slug = request.headers.get("X-authentik-meta-app")
    if not subject or not username or app_slug != settings.authentik_proxy_app_slug:
        raise DomainError(
            "AUTHENTIK_PROXY_HEADERS_REQUIRED",
            "Required Authentik proxy identity headers are missing or invalid",
            401,
        )
    return subject, username


def _proxy_logout_url() -> str:
    return get_settings().authentik_proxy_logout_url


@router.get("/config")
def auth_config() -> dict[str, str | bool]:
    mode = get_settings().auth_mode
    external = mode != AuthMethod.BUILTIN.value
    return {
        "mode": mode,
        "provider": "authentik" if external else "builtin",
        "password_login_enabled": not external,
    }


@router.get("/setup-status")
def setup_status(db: Session = Depends(get_db)) -> dict[str, bool]:
    return {"setup_required": (db.scalar(select(func.count(User.id))) or 0) == 0}


@router.post("/setup", response_model=AuthOut, status_code=201)
def setup(payload: SetupRequest, response: Response, db: Session = Depends(get_db)):
    _require_builtin_mode()
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        raise DomainError("ALREADY_CONFIGURED", "The owner account already exists", 409)
    if not secrets.compare_digest(payload.setup_token, get_settings().setup_token):
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
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _require_builtin_mode()
    username = payload.username.strip().lower()
    source = request.client.host if request.client else "unknown"
    _rate_limit_login(source, username)
    user = db.scalar(select(User).where(func.lower(User.username) == username))
    if not _password_verifiers.acquire(timeout=0.25):
        raise DomainError("LOGIN_BUSY", "Sign-in is temporarily busy. Try again shortly.", 503)
    try:
        password_valid = verify_password(
            payload.password,
            user.password_hash if user is not None else _dummy_password_hash,
        )
    finally:
        _password_verifiers.release()
    if user is None or not user.active or not password_valid:
        raise DomainError("INVALID_CREDENTIALS", "Username or password is incorrect", 401)
    raw_token, csrf = create_session(
        db, user, remember_me=payload.remember_me, auth_method=AuthMethod.BUILTIN.value
    )
    db.commit()
    _set_session_cookie(response, raw_token, persistent=payload.remember_me)
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/logout")
async def logout(
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    encrypted_id_token = context.session.encrypted_id_token
    db.delete(context.session)
    db.commit()
    response.delete_cookie("mp_session", path="/")
    redirect_url: str | None = None
    if settings.auth_mode == AuthMethod.AUTHENTIK_PROXY.value:
        redirect_url = _proxy_logout_url()
    elif settings.auth_mode == AuthMethod.AUTHENTIK_OIDC.value:
        try:
            metadata = await get_provider_metadata(settings)
            redirect_url = end_session_url(settings, metadata, encrypted_id_token)
        except Exception:
            # Local logout has already completed. If discovery is unavailable,
            # the browser can still return to the explicit sign-in screen.
            redirect_url = None
    return {"redirect_url": redirect_url}


@router.post("/proxy/session", response_model=AuthOut)
def proxy_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if settings.auth_mode != AuthMethod.AUTHENTIK_PROXY.value:
        raise DomainError(
            "AUTH_METHOD_DISABLED",
            "Authentik proxy authentication is not active",
            409,
        )
    subject, username = _proxy_headers(request)
    user = resolve_external_identity(
        db,
        auth_method=AuthMethod.AUTHENTIK_PROXY.value,
        issuer=normalize_issuer(settings.authentik_proxy_instance_url),
        subject=subject,
        claimed_username=username,
    )
    raw_token, csrf = create_session(
        db,
        user,
        auth_method=AuthMethod.AUTHENTIK_PROXY.value,
    )
    db.commit()
    _set_session_cookie(response, raw_token)
    logger.info(
        "external proxy session created",
        extra={"auth_mode": settings.auth_mode, "user_id": user.id},
    )
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.get("/oidc/login")
async def oidc_login(return_to: str | None = Query(default=None)):
    settings = get_settings()
    if settings.auth_mode != AuthMethod.AUTHENTIK_OIDC.value:
        raise DomainError(
            "AUTH_METHOD_DISABLED",
            "Authentik OIDC authentication is not active",
            409,
        )
    try:
        url, transaction = await authorization_url(settings, sanitize_return_path(return_to))
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "AUTHENTIK_PROVIDER_UNAVAILABLE",
            "Authentik is temporarily unavailable; try again shortly",
            503,
        ) from exc
    redirect = RedirectResponse(url=url, status_code=302)
    redirect.set_cookie(
        OIDC_TRANSACTION_COOKIE,
        transaction,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=300,
        path="/",
    )
    return redirect


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if settings.auth_mode != AuthMethod.AUTHENTIK_OIDC.value:
        raise DomainError(
            "AUTH_METHOD_DISABLED",
            "Authentik OIDC authentication is not active",
            409,
        )
    transaction = transaction_from_cookie(request.cookies.get(OIDC_TRANSACTION_COOKIE), settings)
    validate_callback_state(transaction, state)
    if error or not code:
        raise DomainError(
            "AUTHENTIK_INVALID_CALLBACK",
            "Authentik did not complete sign-in; try again",
            400,
        )
    try:
        metadata = await get_provider_metadata(settings)
        token = await exchange_code(
            settings,
            metadata,
            code=code,
            code_verifier=transaction["code_verifier"],
        )
        claims = await validate_jwt(token["id_token"], metadata, settings)
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "AUTHENTIK_PROVIDER_UNAVAILABLE",
            "Authentik could not complete sign-in right now; try again shortly",
            503,
        ) from exc
    if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(
        claims["nonce"], transaction["nonce"]
    ):
        raise DomainError(
            "AUTHENTIK_INVALID_CALLBACK",
            "Authentik returned an invalid sign-in response; start again",
            400,
        )
    username = claim_username(claims)
    if username is None:
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise DomainError(
                "AUTHENTIK_USERNAME_REQUIRED",
                "Authentik did not provide a preferred username for this account",
                403,
            )
        userinfo = await fetch_userinfo(metadata, access_token)
        validate_userinfo_subject(claims, userinfo)
        username = claim_username(userinfo)
        if username is None:
            raise DomainError(
                "AUTHENTIK_USERNAME_REQUIRED",
                "Authentik did not provide a preferred username for this account",
                403,
            )
    issuer = normalize_issuer(metadata["issuer"])
    user = resolve_external_identity(
        db,
        auth_method=OIDC_AUTH_METHOD,
        issuer=issuer,
        subject=claims["sub"],
        claimed_username=username,
    )
    sid = claims.get("sid") if isinstance(claims.get("sid"), str) else None
    raw_token, _csrf = create_session(
        db,
        user,
        auth_method=OIDC_AUTH_METHOD,
        sid=sid,
        encrypted_id_token=encrypt_value(token["id_token"], settings),
    )
    db.commit()
    logger.info(
        "external OIDC session created",
        extra={"auth_mode": settings.auth_mode, "user_id": user.id},
    )
    redirect = RedirectResponse(url=sanitize_return_path(transaction["return_to"]), status_code=302)
    redirect.set_cookie(
        "mp_session",
        raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/",
    )
    redirect.delete_cookie(OIDC_TRANSACTION_COOKIE, path="/")
    return redirect


@router.post("/oidc/backchannel-logout", status_code=204)
async def oidc_backchannel_logout(
    logout_token: str = Form(...),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if settings.auth_mode != AuthMethod.AUTHENTIK_OIDC.value:
        raise DomainError(
            "AUTH_METHOD_DISABLED",
            "Authentik OIDC authentication is not active",
            409,
        )
    metadata = await get_provider_metadata(settings)
    claims = await validate_jwt(logout_token, metadata, settings, require_logout_claims=True)
    issuer = normalize_issuer(metadata["issuer"])
    jti = claims["jti"]
    jti_hash = hashlib.sha256(jti.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    db.execute(delete(OidcLogoutReplay).where(OidcLogoutReplay.expires_at <= now))
    replay = db.scalar(
        select(OidcLogoutReplay).where(
            OidcLogoutReplay.issuer == issuer,
            OidcLogoutReplay.jti_hash == jti_hash,
        )
    )
    if replay is not None:
        db.commit()
        return Response(status_code=204)
    expires_at = datetime.fromtimestamp(
        claims.get("exp", int(time.time()) + 300), timezone.utc
    )
    db.add(
        OidcLogoutReplay(
            issuer=issuer,
            jti_hash=jti_hash,
            expires_at=expires_at,
        )
    )
    sid = claims.get("sid") if isinstance(claims.get("sid"), str) else None
    if sid:
        db.execute(
            delete(UserSession).where(
                UserSession.auth_method == AuthMethod.AUTHENTIK_OIDC.value,
                UserSession.sid == sid,
            )
        )
    else:
        identity = db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.auth_method == AuthMethod.AUTHENTIK_OIDC.value,
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == claims["sub"],
            )
        )
        if identity is not None:
            db.execute(
                delete(UserSession).where(
                    UserSession.auth_method == AuthMethod.AUTHENTIK_OIDC.value,
                    UserSession.user_id == identity.user_id,
                )
            )
    try:
        db.commit()
    except Exception:
        db.rollback()
        # A simultaneous delivery may have inserted the same replay key. It
        # is safe to treat that delivery as already processed.
        existing = db.scalar(
            select(OidcLogoutReplay).where(
                OidcLogoutReplay.issuer == issuer,
                OidcLogoutReplay.jti_hash == jti_hash,
            )
        )
        if existing is None:
            raise
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def me(
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    _renew_persistent_session(response, context, db)
    return context.user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserPreferencesUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if payload.ingredient_locale is not None:
        context.user.ingredient_locale = payload.ingredient_locale.value
    if payload.method_view_preference is not None:
        context.user.method_view_preference = payload.method_view_preference.value
    if payload.measurement_system is not None:
        context.user.measurement_system = payload.measurement_system.value
    if payload.method_tutorial_version_seen is not None:
        context.user.method_tutorial_version_seen = payload.method_tutorial_version_seen
    context.user.version += 1
    db.commit()
    db.refresh(context.user)
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
    request: Request,
    mp_session: str | None = Cookie(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),
):
    _require_builtin_mode()
    context = _manual_authenticated_context(request, mp_session, csrf_token, db)
    if not verify_password(payload.current_password, context.user.password_hash):
        raise DomainError("INVALID_PASSWORD", "The current password is incorrect", 403)
    context.user.password_hash = hash_password(payload.new_password)
    context.user.must_change_password = False
    context.user.version += 1
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == context.user.id,
            UserSession.id != context.session.id,
        )
    )
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
    request: Request,
    mp_session: str | None = Cookie(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),
):
    _require_builtin_mode()
    context = _manual_authenticated_context(
        request, mp_session, csrf_token, db, owner=True
    )
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
