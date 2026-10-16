"""Tests for actual route metadata in usage and error rows."""
import json
import os
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_proxy as P

PASS = FAIL = 0


def check(label, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


class Account:
    uid = "cn-usage-1"
    realm = "cn"


tmp = tempfile.mkdtemp()
original = (P.USAGE_DIR, P.USAGE_LOG, P.USAGE_SUMMARY, P._usage,
            P.CURRENT_REALM, P.POOL)
try:
    P.USAGE_DIR = tmp
    P.USAGE_LOG = os.path.join(tmp, "usage.jsonl")
    P.USAGE_SUMMARY = os.path.join(tmp, "usage-summary.json")
    P._usage = P._empty_stats()
    P.CURRENT_REALM = "intl"
    P.POOL = type("Pool", (), {"get": lambda self, uid: Account() if uid == Account.uid else None})()

    print("[1] usage rows retain the selected account realm and route metadata")
    row = P.record_usage(
        "shared", {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        account=Account.uid, route_reason="health", retry_count=1, failover=True,
    )
    check("usage row uses account realm over CURRENT_REALM", row.get("realm") == "cn", row)
    check("selected realm is explicit", row.get("selected_realm") == "cn", row)
    check("selected account is explicit", row.get("selected_account") == Account.uid, row)
    check("route reason is persisted", row.get("route_reason") == "health", row)
    check("retry count is persisted", row.get("retry_count") == 1, row)
    check("failover flag is persisted", row.get("failover") is True, row)

    print()
    print("[2] error rows retain route metadata without secrets")
    error = P.record_error(
        "shared", 502, "upstream failed", realm="cn", account=Account.uid,
        route_reason="failover", retry_count=2, failover=True,
    )
    check("error row records realm", error.get("selected_realm") == "cn", error)
    check("error row records account", error.get("selected_account") == Account.uid, error)
    check("error route reason is persisted", error.get("route_reason") == "failover", error)
    check("error retry count is persisted", error.get("retry_count") == 2, error)
    check("error failover flag is persisted", error.get("failover") is True, error)

    with open(P.USAGE_LOG, encoding="utf-8") as fh:
        raw = fh.read()
    check("usage log contains no bearer token", "Bearer " not in raw and "accessToken" not in raw, raw)
    parsed = [json.loads(line) for line in raw.splitlines() if line.strip()]
    check("both rows are JSON serializable", len(parsed) == 2, parsed)
finally:
    P.USAGE_DIR, P.USAGE_LOG, P.USAGE_SUMMARY, P._usage, P.CURRENT_REALM, P.POOL = original

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
