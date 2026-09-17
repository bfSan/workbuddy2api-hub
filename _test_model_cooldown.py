"""Tests for per-model account cooldown (PATCH wb-hub-model-cooldown).

No network: builds Account objects in-memory and checks that a 429 on one
model freezes only that model, leaving the account usable for other models.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_accounts

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
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
