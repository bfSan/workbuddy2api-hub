"""Tests for deterministic cross-realm route planning and affinity."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_accounts
import wb_routing

PASS = FAIL = 0


def check(label, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


print("[1] exclusive models and hard key policies")
intl_only = wb_routing.plan_realms("gpt-6-astra", ("intl",), key_realm="auto")
check("exclusive intl model routes to intl", [x.realm for x in intl_only] == ["intl"], intl_only)
try:
    wb_routing.plan_realms("gpt-6-astra", ("intl",), key_realm="cn")
except ValueError as exc:
    check("incompatible cn policy is rejected", "cn" in str(exc), exc)
else:
    check("incompatible cn policy is rejected", False, "no error")

print()
print("[2] shared models prefer affinity and healthy realms")
affinity = wb_routing.plan_realms(
    "shared", ("intl", "cn"), key_realm="auto", affinity_realm="cn",
    healthy_realms=("intl", "cn"),
)
check("valid affinity is first", affinity[0].realm == "cn" and affinity[0].reason == "affinity", affinity)
stable_a = wb_routing.plan_realms("stable", ("intl", "cn"), healthy_realms=("intl", "cn"))
stable_b = wb_routing.plan_realms("stable", ("intl", "cn"), healthy_realms=("intl", "cn"))
check("healthy tie-break is deterministic", stable_a == stable_b, (stable_a, stable_b))

print()
print("[3] auto policy falls back and unknown accounts are excluded")
fallback = wb_routing.plan_realms("shared", ("intl", "cn"), healthy_realms=("cn",))
check("only healthy realm is first", [x.realm for x in fallback] == ["cn", "intl"], fallback)
pool = wb_accounts.AccountPool(".")
pool.accounts = [
    wb_accounts.Account({"uid": "intl", "realm": "intl", "accessToken": "tok"}),
    wb_accounts.Account({"uid": "cn", "realm": "cn", "accessToken": "tok"}),
    wb_accounts.Account({"uid": "unknown", "realm": "unknown", "accessToken": "tok"}),
]
health = pool.realm_health()
check("known realms are counted", health.get("intl") == 1 and health.get("cn") == 1, health)
check("unknown realm is excluded", "unknown" not in health, health)
check("allow list narrows health", pool.realm_health(allow={"cn"}) == {"cn": 1}, pool.realm_health(allow={"cn"}))

print()
print("[4] route affinity stores realm and uid with expiry")
aff = wb_accounts.SessionAffinity(ttl=0.01, max_entries=10)
aff.bind_route("session", "cn", "uid-cn")
route = aff.get_route("session")
check("route stores realm and uid", route == {"realm": "cn", "uid": "uid-cn"}, route)
time.sleep(0.03)
check("expired route is removed", aff.get_route("session") is None)

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
