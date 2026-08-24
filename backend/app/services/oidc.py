"""Small, provider-agnostic Authentik OIDC client used by the auth routes."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jws import extract_compact

from ..config import Settings
from ..errors import DomainError
from ..services.integration_credentials import decrypt_value, encrypt_value


OIDC_SCOPE = "openid profile email"
OIDC_TRANSACTION_COOKIE = "mp_oidc_tx"
OIDC_TRANSACTION_MAX_AGE = 300
OIDC_HTTP_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
OIDC_AUTH_METHOD = "authentik_oidc"
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"
SUPPORTED_SIGNING_ALGORITHMS = {
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
}

_metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, KeySet] = {}
_cache_lock = threading.Lock()
_used_states: dict[str, float] = {}


class OidcProviderFailure(Exception):
    """Internal error that never carries provider response bodies."""


def _provider_failure(detail: str = "Authentik is temporarily unavailable") -> DomainError:
    return DomainError("AUTHENTIK_PROVIDER_UNAVAILABLE", detail, 503)


def _safe_provider_url(value: str, *, allow_query: bool = False) -> str:
    candidate = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise OidcProviderFailure
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise OidcProviderFailure from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (parsed.query and not allow_query)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise OidcProviderFailure
    if parsed.scheme != "https" and parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise OidcProviderFailure
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query if allow_query else "", ""))


def _required_metadata(metadata: dict[str, Any], name: str) -> str:
    value = metadata.get(name)
    if not isinstance(value, str) or not value.strip():
        raise OidcProviderFailure
    return _safe_provider_url(value)


async def _get_json(url: str, *, authorization: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    try:
        async with httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:
        raise OidcProviderFailure from exc
    if not isinstance(payload, dict):
        raise OidcProviderFailure
    return payload


async def get_provider_metadata(settings: Settings, *, refresh: bool = False) -> dict[str, Any]:
    discovery_url = settings.authentik_oidc_discovery_url
    now = time.monotonic()
    with _cache_lock:
        cached = _metadata_cache.get(discovery_url)
        if not refresh and cached and cached[0] > now:
            return cached[1]
    try:
        payload = await _get_json(discovery_url)
        issuer = _safe_provider_url(str(payload.get("issuer", "")))
        metadata = {
            **payload,
            "issuer": issuer,
            "authorization_endpoint": _required_metadata(payload, "authorization_endpoint"),
            "token_endpoint": _required_metadata(payload, "token_endpoint"),
            "jwks_uri": _required_metadata(payload, "jwks_uri"),
        }
        if payload.get("userinfo_endpoint"):
            metadata["userinfo_endpoint"] = _required_metadata(payload, "userinfo_endpoint")
        if payload.get("end_session_endpoint"):
            metadata["end_session_endpoint"] = _required_metadata(payload, "end_session_endpoint")
    except OidcProviderFailure as exc:
        raise _provider_failure() from exc
    with _cache_lock:
        _metadata_cache[discovery_url] = (now + 300, metadata)
    return metadata


async def _get_jwks(metadata: dict[str, Any], *, refresh: bool = False) -> KeySet:
    issuer = metadata["issuer"]
    with _cache_lock:
        if not refresh and issuer in _jwks_cache:
            return _jwks_cache[issuer]
    try:
        payload = await _get_json(metadata["jwks_uri"])
        keys = KeySet.import_key_set(payload)
    except (OidcProviderFailure, ValueError, TypeError) as exc:
        raise _provider_failure() from exc
    with _cache_lock:
        _jwks_cache[issuer] = keys
    return keys


def _claims_error() -> DomainError:
    return DomainError(
        "AUTHENTIK_INVALID_CALLBACK",
        "Authentik returned an invalid identity response; start sign-in again",
        400,
    )


async def validate_jwt(
    token_value: str,
    metadata: dict[str, Any],
    settings: Settings,
    *,
    require_logout_claims: bool = False,
) -> dict[str, Any]:
    if not isinstance(token_value, str) or not token_value or len(token_value) > 32_768:
        raise _claims_error()
    try:
        compact = extract_compact(token_value.encode("ascii"))
        header = compact.headers()
        algorithm = header.get("alg")
        if algorithm not in SUPPORTED_SIGNING_ALGORITHMS:
            raise JoseError("unsupported signing algorithm")
        key_set = await _get_jwks(metadata)
        try:
            decoded = jwt.decode(token_value, key_set, algorithms=SUPPORTED_SIGNING_ALGORITHMS)
        except Exception:
            # Authentik rotates signing keys. One bounded refresh is enough to
            # accept a newly published key without turning key lookup into an
            # unbounded provider request loop.
            key_set = await _get_jwks(metadata, refresh=True)
            decoded = jwt.decode(token_value, key_set, algorithms=SUPPORTED_SIGNING_ALGORITHMS)
        claims = decoded.claims
        registry_options: dict[str, Any] = {
            "iss": {"essential": True, "value": metadata["issuer"]},
            "aud": {"essential": True, "values": [settings.authentik_oidc_client_id]},
            "iat": {"essential": True},
        }
        if require_logout_claims:
            registry_options["jti"] = {"essential": True}
            registry_options["exp"] = {"essential": True}
        else:
            registry_options["sub"] = {"essential": True}
            registry_options["exp"] = {"essential": True}
        registry = jwt.JWTClaimsRegistry(**registry_options)
        registry.validate(claims)
        if not require_logout_claims and (
            not isinstance(claims.get("sub"), str) or not claims["sub"].strip()
        ):
            raise JoseError("missing subject")
        audience = claims.get("aud")
        if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != settings.authentik_oidc_client_id:
            raise JoseError("invalid authorized party")
        if require_logout_claims:
            if "nonce" in claims:
                raise JoseError("logout token must not contain nonce")
            jti = claims.get("jti")
            events = claims.get("events")
            if not isinstance(jti, str) or not jti.strip() or not isinstance(events, dict):
                raise JoseError("invalid logout claims")
            if events.get(BACKCHANNEL_LOGOUT_EVENT) != {}:
                raise JoseError("invalid logout event")
            if not (
                isinstance(claims.get("sid"), str)
                and 0 < len(claims["sid"].strip()) <= 512
                or isinstance(claims.get("sub"), str)
                and 0 < len(claims["sub"].strip()) <= 512
            ):
                raise JoseError("logout subject missing")
        return claims
    except DomainError:
        raise
    except Exception as exc:
        raise _claims_error() from exc


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _code_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def sanitize_return_path(value: str | None) -> str:
    if not value:
        return "/week"
    candidate = value.strip()
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        return "/week"
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return "/week"
    if parsed.path in {
        "/api/v1/auth/oidc/login",
        "/api/v1/auth/oidc/callback",
        "/api/v1/auth/oidc/backchannel-logout",
        "/api/v1/auth/logout",
    }:
        return "/week"
    return candidate


def _transaction_cookie_payload(value: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = json.loads(decrypt_value(value, settings))
    except Exception as exc:
        raise _claims_error() from exc
    if not isinstance(payload, dict):
        raise _claims_error()
    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, int) or issued_at < int(time.time()) - OIDC_TRANSACTION_MAX_AGE or issued_at > int(time.time()) + 30:
        raise DomainError("AUTHENTIK_LOGIN_EXPIRED", "The Authentik sign-in request expired; start again", 400)
    if not all(isinstance(payload.get(name), str) and payload[name] for name in ("state", "nonce", "code_verifier", "return_to")):
        raise _claims_error()
    return payload


def make_transaction_cookie(payload: dict[str, Any], settings: Settings) -> str:
    return encrypt_value(json.dumps(payload, separators=(",", ":")), settings)


async def authorization_url(settings: Settings, return_to: str) -> tuple[str, str]:
    metadata = await get_provider_metadata(settings)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    redirect_uri = f"{settings.public_url}/api/v1/auth/oidc/callback"
    client = AsyncOAuth2Client(
        client_id=settings.authentik_oidc_client_id,
        client_secret=settings.authentik_oidc_client_secret,
        scope=OIDC_SCOPE,
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
    )
    try:
        url, returned_state = client.create_authorization_url(
            metadata["authorization_endpoint"],
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )
    finally:
        await client.aclose()
    if returned_state != state:
        raise _provider_failure("Authentik returned an invalid authorization request")
    payload = {
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "issued_at": int(time.time()),
        "return_to": sanitize_return_path(return_to),
    }
    _used_states.pop(state, None)
    return url, make_transaction_cookie(payload, settings)


async def exchange_code(
    settings: Settings,
    metadata: dict[str, Any],
    *,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    redirect_uri = f"{settings.public_url}/api/v1/auth/oidc/callback"
    client = AsyncOAuth2Client(
        client_id=settings.authentik_oidc_client_id,
        client_secret=settings.authentik_oidc_client_secret,
        scope=OIDC_SCOPE,
        redirect_uri=redirect_uri,
        code_challenge_method="S256",
    )
    try:
        try:
            token = await client.fetch_token(
                metadata["token_endpoint"],
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        except Exception as exc:
            raise OidcProviderFailure from exc
    finally:
        await client.aclose()
    if not isinstance(token, dict) or not isinstance(token.get("id_token"), str):
        raise OidcProviderFailure
    return token


async def fetch_userinfo(metadata: dict[str, Any], access_token: str) -> dict[str, Any]:
    endpoint = metadata.get("userinfo_endpoint")
    if not endpoint or not isinstance(access_token, str) or not access_token:
        raise _claims_error()
    try:
        payload = await _get_json(endpoint, authorization=f"Bearer {access_token}")
    except OidcProviderFailure as exc:
        raise _provider_failure() from exc
    if not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
        raise _claims_error()
    return payload


def claim_username(claims: dict[str, Any]) -> str | None:
    username = claims.get("preferred_username")
    return username.strip() if isinstance(username, str) and username.strip() else None


def consume_state(state: str) -> bool:
    now = time.monotonic()
    expired = [key for key, expiry in _used_states.items() if expiry <= now]
    for key in expired:
        _used_states.pop(key, None)
    if state in _used_states:
        return False
    _used_states[state] = now + OIDC_TRANSACTION_MAX_AGE
    return True


def fixed_post_logout_url(settings: Settings) -> str:
    return f"{settings.public_url}/login?{urlencode({'logged_out': '1'})}"


def end_session_url(settings: Settings, metadata: dict[str, Any], encrypted_id_token: str | None) -> str | None:
    endpoint = metadata.get("end_session_endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return None
    try:
        endpoint = _safe_provider_url(endpoint, allow_query=True)
    except OidcProviderFailure:
        return None
    params = {"post_logout_redirect_uri": fixed_post_logout_url(settings)}
    if encrypted_id_token:
        try:
            id_token = decrypt_value(encrypted_id_token, settings)
        except Exception:
            id_token = ""
        if id_token:
            params["id_token_hint"] = id_token
    separator = "&" if urlsplit(endpoint).query else "?"
    return f"{endpoint}{separator}{urlencode(params)}"


def transaction_from_cookie(value: str | None, settings: Settings) -> dict[str, Any]:
    if not value:
        raise DomainError(
            "AUTHENTIK_LOGIN_REQUIRED",
            "The Authentik sign-in request is missing or expired; start again",
            400,
        )
    return _transaction_cookie_payload(value, settings)


def validate_callback_state(payload: dict[str, Any], state: str | None) -> None:
    if not state or not secrets.compare_digest(payload["state"], state) or not consume_state(state):
        raise DomainError("AUTHENTIK_STATE_MISMATCH", "The Authentik sign-in response could not be verified", 400)


def validate_userinfo_subject(claims: dict[str, Any], userinfo: dict[str, Any]) -> None:
    if userinfo.get("sub") != claims.get("sub"):
        raise _claims_error()
