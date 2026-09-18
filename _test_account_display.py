"""Tests for account alias display across dashboard API surfaces."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_accounts
import wb_proxy as P
import wb_settings

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


def account(uid, nickname, realm="cn"):
    return wb_accounts.Account({
        "uid": uid,
        "nickname": nickname,
        "realm": realm,
        "accessToken": "token",
    })


tmp = tempfile.mkdtemp()
P.ACCOUNTS_DIR = tmp
P.USAGE_LOG = os.path.join(tmp, "usage.jsonl")
P._WB_PATCH_ALIAS_CACHE = {"stamp": 0, "data": {}}
wb_settings.set_account_aliases(tmp, {"u1": "研发主号"})

first = account("u1", "upstream-one")
second = account("u2", "upstream-two")
pool = wb_accounts.AccountPool(tmp)
pool.accounts = [first, second]
P.POOL = pool

print("[1] account_views exposes alias and keeps nickname fallback")
views = {row["uid"]: row for row in P.account_views()}
check("ldap alias attached", views["u1"].get("alias") == "研发主号", views["u1"])
check("fallback account has no alias", views["u2"].get("alias") == "", views["u2"])
check("upstream nickname remains available", views["u1"].get("nickname") == "upstream-one")

print()
print("[2] usage snapshot maps uid to display alias")
snap = P._usage_snapshot_uncached("cn")
accounts_map = snap.get("accounts_map") or {}
check("alias is available by uid", accounts_map["u1"].get("alias") == "研发主号", accounts_map.get("u1"))
check("nickname fallback remains available", accounts_map["u2"].get("nickname") == "upstream-two")

print()
print("[3] recent usage rows include display aliases")
rows = [
    {"at": 1, "model": "hy3", "account": "u1", "total_tokens": 10},
    {"at": 2, "model": "hy3", "account": "u2", "total_tokens": 20},
]
with open(P.USAGE_LOG, "w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row) + "\n")
recent = P.recent_usage(limit=10, realm="cn")["rows"]
by_account = {row["account"]: row for row in recent}
check("aliased row carries account_name", by_account["u1"].get("account_name") == "研发主号", by_account["u1"])
check("aliased row carries account_alias", by_account["u1"].get("account_alias") == "研发主号", by_account["u1"])
check("unaliased row falls back to nickname",
      by_account["u2"].get("account_name") == "upstream-two", by_account["u2"])

print()
print("[4] settings account options carry display aliases")
settings = P.runtime_settings_view()
options = {row["uid"]: row for row in settings.get("account_options", [])}
check("settings option exposes alias", options["u1"].get("alias") == "研发主号", options["u1"])
check("settings option keeps nickname fallback",
      options["u2"].get("nickname") == "upstream-two", options["u2"])

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
