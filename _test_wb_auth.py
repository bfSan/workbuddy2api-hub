import time
from urllib.parse import parse_qs, urlparse

import wb_auth


def check(name, condition, detail=None):
    if not condition:
        raise SystemExit("FAIL: %s%s" % (name, (" -> %r" % detail) if detail is not None else ""))
    print("PASS: %s" % name)

value = wb_auth.build_authorize_url("https://aac.example", "workbuddy2api-hub", "https://wb.example/auth/callback", "state-1", "challenge-1")
query = parse_qs(urlparse(value).query)
check("authorize URL path", urlparse(value).path == "/oauth/authorize")
check("authorize URL client", query["client_id"] == ["workbuddy2api-hub"])
check("authorize URL PKCE", query["code_challenge_method"] == ["S256"])

old_post = wb_auth._post_json
try:
    wb_auth._post_json = lambda *args, **kwargs: {"active": True, "aud": "workbuddy2api-hub", "client_id": "workbuddy2api-hub", "sub": "aac-1", "grants": ["workbuddy:access"]}
    claims = wb_auth.introspect_access_token("https://aac.example", "token", "workbuddy2api-hub")
    check("access scope maps user", claims.aac_user_id == "aac-1" and claims.role == "user")
    wb_auth._post_json = lambda *args, **kwargs: {"active": True, "aud": "other", "client_id": "workbuddy2api-hub", "sub": "aac-1", "grants": ["workbuddy:access"]}
    try:
        wb_auth.introspect_access_token("https://aac.example", "token", "workbuddy2api-hub")
    except wb_auth.AuthError:
        check("wrong audience rejected", True)
    else:
        check("wrong audience rejected", False)
finally:
    wb_auth._post_json = old_post

session = wb_auth.create_oauth_session({"sub": "aac-2", "aud": "workbuddy2api-hub", "client_id": "workbuddy2api-hub", "grants": ["workbuddy:access", "workbuddy:admin"], "exp": int(time.time()) + 100})
principal = wb_auth.resolve_principal({}, {"WB-Session": session["session_id"]}, {session["session_id"]: session})
check("admin scope maps admin", principal.principal_type == "aac-user" and principal.role == "admin")
try:
    wb_auth.resolve_principal({}, {"WB-Session": session["session_id"]}, {session["session_id"]: dict(session, expires_at=time.time() - 1)})
except wb_auth.AuthError:
    check("expired session rejected", True)
else:
    check("expired session rejected", False)
