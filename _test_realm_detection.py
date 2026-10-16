"""Tests for strict WorkBuddy account realm detection."""
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_accounts

PASS = FAIL = 0


def check(label, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


def token(issuer, subject="u1", audience="workbuddy"):
    def enc(value):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return enc({"alg": "none"}) + "." + enc({
        "iss": issuer,
        "sub": subject,
        "aud": audience,
    }) + ".signature"


print("[1] explicit issuer/domain evidence identifies the realm")
intl = wb_accounts.detect_account_realm(
    token("https://www.workbuddy.ai/v2/plugin/auth"), "www.workbuddy.ai"
)
cn = wb_accounts.detect_account_realm(
    token("https://copilot.tencent.com/v2/plugin/auth"), "copilot.tencent.com"
)
check("international issuer/domain", intl[0] == "intl", intl)
check("domestic issuer/domain", cn[0] == "cn", cn)

print()
print("[2] ambiguous and conflicting credentials are quarantined")
unknown = wb_accounts.detect_account_realm(token("https://example.invalid"), "")
conflict = wb_accounts.detect_account_realm(
    token("https://copilot.tencent.com/v2/plugin/auth"), "www.workbuddy.ai"
)
check("missing evidence returns unknown", unknown[0] == "unknown", unknown)
check("conflicting evidence returns unknown", conflict[0] == "unknown", conflict)
check("conflict explains the error", bool(conflict[2]), conflict)
try:
    wb_accounts.get_realm_config("unknown")
except ValueError as exc:
    check("unknown realm cannot resolve an upstream config", "unknown realm" in str(exc), exc)
else:
    check("unknown realm cannot resolve an upstream config", False, "unexpected fallback")

print()
print("[3] explicit token evidence overrides stale stored realm")
account = wb_accounts.Account({
    "uid": "u1",
    "realm": "intl",
    "accessToken": token("https://copilot.tencent.com/v2/plugin/auth"),
    "domain": "copilot.tencent.com",
})
check("token evidence wins over stored realm", account.realm == "cn", account.realm)
check("realm source is persisted in memory", account.realm_source in ("issuer", "issuer+domain"), account.realm_source)
stored_only = wb_accounts.Account({
    "uid": "stored-only",
    "realm": "intl",
    "accessToken": token("https://example.invalid"),
})
check("stored realm alone is quarantined", stored_only.realm == "unknown" and not stored_only.ready(),
      (stored_only.realm, stored_only.realm_source, stored_only.realm_error))

print()
print("[4] realm source and error survive persistence")
data = account.to_dict()
check("realmSource is serialized", data.get("realmSource") == account.realm_source, data)
check("realmError is serialized", data.get("realmError") == account.realm_error, data)
reloaded = wb_accounts.Account(data)
check("serialized account reloads with cn realm", reloaded.realm == "cn", reloaded.realm)

print()
print("[5] imports reject a valid token with no detectable realm")
try:
    wb_accounts.normalise_import_row({
        "uid": "u-unknown",
        "accessToken": token("https://example.invalid"),
        "domain": "example.invalid",
    })
except ValueError as exc:
    check("unknown import is rejected", "realm" in str(exc).lower(), exc)
else:
    check("unknown import is rejected", False, "import unexpectedly accepted")

print()
print("[6] desktop imports reject unknown credentials")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "unknown.info")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "auth": {"accessToken": token("https://example.invalid"),
                     "domain": "example.invalid"},
            "account": {"uid": "desktop-unknown"},
        }, fh)
    pool = wb_accounts.AccountPool(os.path.join(tmp, "accounts"))
    try:
        pool.import_desktop_credential(path=path)
    except ValueError as exc:
        check("unknown desktop credential is rejected", "realm" in str(exc).lower(), exc)
    else:
        check("unknown desktop credential is rejected", False, "import unexpectedly accepted")
    try:
        pool.import_desktop_credential(path=path, realm="cn")
    except ValueError as exc:
        check("forced realm does not guess unknown desktop credential", "realm" in str(exc).lower(), exc)
    else:
        check("forced realm does not guess unknown desktop credential", False, "forced import unexpectedly accepted")

try:
    wb_accounts.normalise_import_row({
        "uid": "u-forced-unknown",
        "accessToken": token("https://example.invalid"),
        "domain": "example.invalid",
    }, realm="cn")
except ValueError as exc:
    check("forced realm does not guess unknown import", "realm" in str(exc).lower(), exc)
else:
    check("forced realm does not guess unknown import", False, "forced import unexpectedly accepted")

print()
print("[7] refresh re-detects realm and clears stale affinity")
cn_token = token("https://copilot.tencent.com/v2/plugin/auth", subject="refresh-user")
intl_token = token("https://www.workbuddy.ai/v2/plugin/auth", subject="refresh-user")
account = wb_accounts.Account({
    "uid": "refresh-user",
    "accessToken": cn_token,
    "refreshToken": "refresh-secret",
    "domain": "copilot.tencent.com",
})
pool = wb_accounts.AccountPool(tempfile.mkdtemp())
pool.add(account)
pool.affinity.bind_route("refresh-session", "cn", account.uid)
original_http_json = wb_accounts.http_json
try:
    wb_accounts.http_json = lambda *args, **kwargs: {
        "data": {"accessToken": intl_token, "refreshToken": "refresh-secret-2"}
    }
    refreshed = pool.refresh_account(account)
    check("refresh updates account realm", refreshed and account.realm == "intl", account.realm)
    check("refresh clears old affinity", pool.affinity.get_route("refresh-session") is None,
          pool.affinity.get_route("refresh-session"))
    wb_accounts.http_json = lambda *args, **kwargs: {
        "data": {"accessToken": token("https://copilot.tencent.com/v2/plugin/auth"),
                 "domain": "www.workbuddy.ai"}
    }
    refreshed = pool.refresh_account(account)
    check("conflicting refresh quarantines account", refreshed and account.realm == "unknown",
          (account.realm, account.realm_error))
    check("conflicting refresh records a visible error", bool(account.last_error),
          account.last_error)
    check("unknown refreshed account is not ready", account.ready(model="shared") is False,
          account.realm)
finally:
    wb_accounts.http_json = original_http_json

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
