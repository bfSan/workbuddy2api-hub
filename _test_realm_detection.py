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
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
