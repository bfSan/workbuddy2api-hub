"""Tests for upstream credits sync (B) and panel model config (C)."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TMP = tempfile.mkdtemp()
os.environ["ACCOUNTS_DIR"] = TMP
os.environ["WB_PROXY_ACCOUNTS_DIR"] = TMP

import wb_proxy as P
import wb_settings

# wb_proxy.ACCOUNTS_DIR is a module-level constant (repo path); point it at the
# isolated temp dir so panel config reads/writes land there during tests.
P.ACCOUNTS_DIR = TMP

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


print("[1] merge_catalog: upstream meta credits override static catalog")
# pick a model that exists in the static CN catalog
static = {m["id"]: m for m in P.wb_catalog.STATIC_CN_MODELS if m.get("id")}
target = "hy3" if "hy3" in static else list(static)[0]
merged = dict(P.merge_catalog([(target, {"credits": "x9.99 credits"})], realm="cn"))
check("upstream credits override static", merged.get(target, {}).get("credits") == "x9.99 credits",
      merged.get(target, {}).get("credits"))

print()
print("[2] fallback: no upstream meta keeps static credits")
merged2 = dict(P.merge_catalog([], realm="cn"))
check("static credits retained", bool(merged2.get(target, {}).get("credits")),
      merged2.get(target, {}).get("credits"))

print()
print("[3] panel config: hidden removes, order reorders")
base_ids = [m for m, _ in P._wb_patch_pick_env([(target, static[target])], "cn")]
wb_settings.set_model_config(TMP, "cn", [target], [])
hidden_ids = [m for m, _ in P.wb_patch_pick([(target, static[target])], "cn")]
check("hidden model removed by wb_patch_pick", target not in hidden_ids, hidden_ids)

wb_settings.set_model_config(TMP, "cn", [], ["glm-5.3", "hy3"])
order_ids = [m for m, _ in P.wb_patch_pick(
    list(P.merge_catalog([], realm="cn")), "cn")]
if "glm-5.3" in order_ids and "hy3" in order_ids:
    check("custom order respected", order_ids.index("glm-5.3") < order_ids.index("hy3"))
else:
    check("custom order respected (models present)", False, order_ids[:5])

print()
print("[4] no config => identical to env-only behavior")
wb_settings.set_model_config(TMP, "cn", [], [])
plain = P._wb_patch_pick_env(list(P.merge_catalog([], realm="cn")), "cn")
wrapped = P.wb_patch_pick(list(P.merge_catalog([], realm="cn")), "cn")
check("empty config is a no-op", plain == wrapped)

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
