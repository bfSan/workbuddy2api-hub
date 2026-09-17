"""Tests for per-model account cooldown (PATCH wb-hub-model-cooldown).

No network: builds Account objects in-memory and checks that a 429 on one
model freezes only that model, leaving the account usable for other models.
"""
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_accounts
import wb_proxy as P

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


def mk_account(uid="u1", realm="cn", token="tok"):
    return wb_accounts.Account({"uid": uid, "realm": realm, "accessToken": token})


print("[1] a 429 on one model freezes only that model")
a = mk_account()
check("account ready before any error", a.ready() is True)
# 429 => account_wide=False: freeze this model only
a.note_error("HTTP 429", cooldown=300, model="hy4-preview", account_wide=False)
check("global cooldown untouched by model-scoped 429", a.cooldown_until == 0)
check("model hy4-preview is frozen", a.cooldown_until_model("hy4-preview") > time.time())
check("other model glm-5.3 is NOT frozen", a.cooldown_until_model("glm-5.3") == 0)
check("ready(model=hy4-preview) is False", a.ready(model="hy4-preview") is False)
check("ready(model=glm-5.3) is True (per-model)", a.ready(model="glm-5.3") is True)
check("account still globally usable", a.ready() is True)

print()
print("[1b] 401/403 freeze the whole account")
c = mk_account(uid="u3")
c.note_error("HTTP 403", cooldown=60, model="hy4-preview", account_wide=True)
check("global cooldown set for account-level error", c.cooldown_until > time.time())
check("ready(model=glm-5.3) is False", c.ready(model="glm-5.3") is False)

print()
print("[2] clear_error wipes the whole per-model map")
a.clear_error()
check("global cooldown cleared", a.cooldown_until == 0)
check("model map cleared", a.model_cooldowns == {})
check("ready(model=hy4-preview) True after clear", a.ready(model="hy4-preview") is True)

print()
print("[3] modelCooldowns persists via to_dict and reloads (dropping expired)")
b = mk_account(uid="u2")
future = time.time() + 120
b.model_cooldowns = {"hy4-preview": future, "stale-model": time.time() - 5}
d = b.to_dict()
check("to_dict carries modelCooldowns", "modelCooldowns" in d, list(d.keys())[:6])
reloaded = wb_accounts.Account(d)
check("future cooldown survives reload", "hy4-preview" in reloaded.model_cooldowns)
check("expired cooldown dropped on reload", "stale-model" not in reloaded.model_cooldowns)

print()
print("[4] public() exposes per-model cooldown detail for the dashboard")
pub = b.public()
check("public has cooldowns list", isinstance(pub.get("cooldowns"), list))
entry = (pub.get("cooldowns") or [{}])[0]
check("cooldown entry has model+seconds",
      entry.get("model") == "hy4-preview" and entry.get("seconds") > 0, entry)

print()
print("[5] preset aliases are preserved for upstream routing")
check("fast preset passes through", P.resolve_preset_model("fast-model") == "fast-model")
check("balanced preset passes through", P.resolve_preset_model("balanced-model") == "balanced-model")
check("deep preset passes through", P.resolve_preset_model("deep-model") == "deep-model")
check("normal model passes through", P.resolve_preset_model("hy3") == "hy3")
check("preset keeps requested id in usage", P.usage_model_label("fast-model", "hy3") == "fast-model")

print()
print("[6] account allow-list is applied before selection")
pool = wb_accounts.AccountPool(".")
blocked = mk_account(uid="blocked", token="tok")
preferred = mk_account(uid="preferred", token="tok")
pool.accounts = [blocked, preferred]
pool._cursor = 0  # the cursor starts on the non-allow-listed account
check("allowed account selected from blocked cursor",
      pool.pick(realm="cn", model="deepseek-v4.1-flash",
                allow={"preferred"}).uid == "preferred")
check("non-allowed account never returned",
      pool.pick(realm="cn", model="deepseek-v4.1-flash",
                allow={"preferred"}).uid != "blocked")

print()
print("[7] allowed account rotates after a model-scoped 429")
allowed = {"first", "second"}
first = mk_account(uid="first", token="tok")
second = mk_account(uid="second", token="tok")
pool.accounts = [first, second]
pool._cursor = 0
picked = pool.pick(realm="cn", model="deepseek-v4.1-flash", allow=allowed)
check("first allowed account selected", picked.uid == "first")
first.note_error("HTTP 429", cooldown=300, model="deepseek-v4.1-flash",
                 account_wide=False)
picked_next = pool.pick(realm="cn", exclude={"first"},
                        model="deepseek-v4.1-flash", allow=allowed)
check("second allowed account is next after 429", picked_next.uid == "second")

print()
print("[8] open_upstream retries the next allow-listed account after HTTP 429")
outsider = mk_account(uid="outsider", token="tok")
first = mk_account(uid="first", token="tok")
second = mk_account(uid="second", token="tok")
pool.accounts = [outsider, first, second]
pool._cursor = 0  # original bug: the outsider consumed the first retry slot
original_pool = P.POOL
original_urlopen = P.urllib.request.urlopen
calls = []


def fake_urlopen(req, timeout=None):
    auth = req.get_header("Authorization") or ""
    uid = req.get_header("X-user-id") or ""
    calls.append(uid)
    if auth == "Bearer tok":
        # Both accounts share this token in the harness, so distinguish by uid.
        if uid == "first":
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                         {}, None)
    return "upstream-response"


try:
    first = mk_account(uid="first", token="tok")
    second = mk_account(uid="second", token="tok")
    pool.accounts = [outsider, first, second]
    pool._cursor = 0
    P.POOL = pool
    P.urllib.request.urlopen = fake_urlopen
    response, selected = P.open_upstream(
        {"model": "deepseek-v4.1-flash",
         "messages": [{"role": "user", "content": "ping"}]},
        target_realm="cn",
        allow={"first", "second"},
    )
    check("open_upstream returns the second account", selected.uid == "second",
          selected.uid)
    check("open_upstream retried after the first 429", len(calls) == 2, calls)
    check("non-allow-listed account was never called",
          all(call in ("first", "second") for call in calls), calls)
    check("open_upstream returned upstream response", response == "upstream-response")
finally:
    P.urllib.request.urlopen = original_urlopen
    P.POOL = original_pool

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
