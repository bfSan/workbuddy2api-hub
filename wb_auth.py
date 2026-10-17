"""AAC OAuth client and hybrid principal resolution for WorkBuddy.

The first phase uses AAC token introspection so this module remains Python
standard-library only. Access tokens never enter browser cookies or persisted
settings; only short lived WorkBuddy sessions do.
"""
import base64
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, asdict
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CLIENT_ID = "workbuddy2api-hub"
REDIRECT_URI = ""
SESSION_TTL = 8 * 60 * 60
AUTH_FRESHNESS = 5 * 60
MAX_SESSIONS = 2048
_sessions = {}
_local_sessions = {}
_lock = threading.RLock()


class AuthError(Exception):
    def __init__(self, code, message=None, status=401):
        self.code = code
        self.status = status
        super().__init__(message or code)


@dataclass(frozen=True)
class PrincipalContext:
    principal_type: str
    workbuddy_user_id: str
    aac_user_id: str
    role: str
    auth_method: str
    scopes: tuple = ()
    session_id: str = ""
    authorization_checked_at: float = 0.0

    def as_dict(self):
        value = asdict(self)
        value["scopes"] = list(self.scopes)
        return value


def build_authorize_url(aac_url, client_id, redirect_uri, state, code_challenge):
    base = str(aac_url or "").rstrip("/") + "/oauth/authorize"
    return base + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "workbuddy:access workbuddy:admin",
        "state": state,
        "nonce": secrets.token_urlsafe(18),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


def exchange_code(aac_url, client_id, redirect_uri, code, code_verifier):
    return _post_json(str(aac_url).rstrip("/") + "/oauth/token", {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    })


def introspect_access_token(aac_url, token, expected_audience):
    if not token:
        raise AuthError("WB_AAC_TOKEN_INVALID")
    try:
        claims = _post_json(str(aac_url).rstrip("/") + "/oauth/introspect", {"token": token, "client_id": CLIENT_ID})
    except Exception as exc:
        if isinstance(exc, AuthError):
            raise
        raise AuthError("WB_AAC_UNAVAILABLE", str(exc), 503)
    return principal_from_claims(claims, expected_audience, auth_method="oauth")


def principal_from_claims(claims, expected_audience, auth_method="oauth"):
    if not isinstance(claims, dict) or not claims.get("active"):
        raise AuthError("WB_AAC_TOKEN_INVALID")
    if claims.get("aud") != expected_audience or claims.get("client_id") != CLIENT_ID:
        raise AuthError("WB_AAC_TOKEN_INVALID")
    grants = tuple(sorted(set(str(x).strip() for x in claims.get("grants") or [] if str(x).strip())))
    if "workbuddy:access" not in grants and "*" not in grants:
        raise AuthError("WB_AAC_SCOPE_MISSING", status=403)
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise AuthError("WB_AAC_TOKEN_INVALID")
    exp = claims.get("exp")
    if exp is not None and float(exp) <= time.time():
        raise AuthError("WB_AAC_TOKEN_INVALID")
    role = "admin" if "workbuddy:admin" in grants or "*" in grants else "user"
    return PrincipalContext("aac-user", sub, sub, role, auth_method, grants, "", time.time())


def create_oauth_session(principal_claims, now=None):
    now = float(time.time() if now is None else now)
    principal = principal_claims if isinstance(principal_claims, PrincipalContext) else principal_from_claims({"active": True, **principal_claims}, principal_claims.get("aud", "workbuddy2api-hub"))
    session_id = secrets.token_urlsafe(32)
    session = {
        "session_id": session_id,
        "principal_type": "aac-user",
        "workbuddy_user_id": principal.workbuddy_user_id,
        "aac_user_id": principal.aac_user_id,
        "role": principal.role,
        "auth_method": "oauth",
        "scopes": list(principal.scopes),
        "authorization_checked_at": now,
        "created_at": now,
        "expires_at": now + SESSION_TTL,
    }
    with _lock:
        _sessions[session_id] = session
        _trim(_sessions)
    return dict(session)


def create_local_admin_session(value=None, now=None):
    now = float(time.time() if now is None else now)
    value = dict(value or {})
    session_id = str(value.get("session_id") or secrets.token_urlsafe(24))
    session = {
        "session_id": session_id,
        "principal_type": "local-admin",
        "workbuddy_user_id": "local-admin",
        "aac_user_id": "",
        "role": "admin",
        "auth_method": "local-panel",
        "scopes": ["local-admin"],
        "authorization_checked_at": now,
        "created_at": now,
        "expires_at": float(value.get("expires_at") or now + SESSION_TTL),
    }
    with _lock:
        _local_sessions[session_id] = session
        _trim(_local_sessions)
    return dict(session)


def resolve_principal(headers, cookies, local_state, now=None, local_sessions=None):
    now = float(time.time() if now is None else now)
    cookies = cookies or {}
    local_sessions = local_sessions if local_sessions is not None else _local_sessions
    panel_id = cookies.get("WB-Panel-Session") or headers.get("X-Panel-Session")
    if panel_id:
        session = local_sessions.get(panel_id)
        if session and float(session.get("expires_at", 0)) > now:
            return _principal_from_session(session)
        raise AuthError("WB_SESSION_EXPIRED")
    session_id = cookies.get("WB-Session") or headers.get("X-WB-Session")
    if session_id:
        store = local_state if isinstance(local_state, dict) and session_id in local_state else _sessions
        session = store.get(session_id)
        if not session or float(session.get("expires_at", 0)) <= now:
            raise AuthError("WB_SESSION_EXPIRED")
        return _principal_from_session(session)
    return PrincipalContext("anonymous", "", "", "", "none", (), "", now)


def _principal_from_session(session):
    return PrincipalContext(str(session.get("principal_type") or ""), str(session.get("workbuddy_user_id") or ""), str(session.get("aac_user_id") or ""), str(session.get("role") or ""), str(session.get("auth_method") or ""), tuple(session.get("scopes") or ()), str(session.get("session_id") or ""), float(session.get("authorization_checked_at") or 0))


def _post_json(url, payload, timeout=10):
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise AuthError("WB_AAC_TOKEN_INVALID" if exc.code in (400, 401, 403) else "WB_AAC_UNAVAILABLE", status=exc.code)
    except (URLError, OSError, ValueError) as exc:
        raise AuthError("WB_AAC_UNAVAILABLE", str(exc), 503)
    if not isinstance(data, dict):
        raise AuthError("WB_AAC_TOKEN_INVALID")
    return data


def _trim(store):
    if len(store) <= MAX_SESSIONS:
        return
    oldest = sorted(store.items(), key=lambda item: float(item[1].get("created_at", 0)))[: len(store) - MAX_SESSIONS]
    for key, _ in oldest:
        store.pop(key, None)
