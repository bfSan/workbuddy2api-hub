"""End-to-end regression for the two reported panel bugs.

Scenario mirrors the deployment (WB_MODEL_SET=official, cn realm, a stale
mounted desktop-app cache file, and a live upstream payload):

  Bug 1: pressing 从上游同步 did not update the model list / multipliers,
         because the fresh catalog fetched by sync_models() was discarded and
         every reader re-derived the list from the stale product-config file.
  Bug 2: un-hiding a model in the panel did nothing when the model existed
         only upstream, because the panel pool was built from the already
         filtered in-memory cache instead of the full catalog.

Fixtures are inline so the test never touches the network or the real home
directory. Run:  python3 _test_model_sync_e2e.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["ACCOUNTS_DIR"] = TMP
os.environ["WB_PROXY_ACCOUNTS_DIR"] = TMP
os.environ["WB_PROXY_DEFAULT_REALM"] = "cn"
os.environ["WB_MODEL_SET"] = "official"
sys.path.insert(0, HERE)

import wb_proxy as P
import wb_settings

P.ACCOUNTS_DIR = TMP

# The mounted desktop-app cache: stale multipliers, missing newer models.
STALE_PRODUCT = {
    "models": [
        {"id": "hy3", "credits": "x0.00", "supportsToolCall": True},
        {"id": "glm-5.2", "credits": "x0.79", "tags": ["craft"]},
        {"id": "deepseek-v4.1-flash", "credits": "x0.03"},
    ],
}
# What the upstream endpoint reports right now: re-priced model + new models.
LIVE_PAYLOAD = {
    "data": {
        "models": [
            {"id": "hy3", "credits": "x0.00 credits",
             "tags": ["craft", "badge:限时免费:#FF0000"]},
            {"id": "glm-5.2", "credits": "x0.79 credits",
             "tags": ["craft", "badge:夜间折扣:#1E90FF"]},
            {"id": "deepseek-v4.1-flash", "credits": "x0.11 credits"},
            {"id": "glm-4.7", "credits": "x0.23 credits"},
            {"id": "step-5-preview", "credits": "x0.05 credits"},
        ],
    },
}

_orig_product = P.read_product_config_models
_orig_endpoint = P.fetch_endpoint_models
P.read_product_config_models = lambda realm=None: P.parse_product_config_models(STALE_PRODUCT)
P.fetch_endpoint_models = lambda realm=None, force=False: (
    P.parse_endpoint_model_payload(LIVE_PAYLOAD) if force else [])

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


print("[1] before sync the panel shows the stale mounted snapshot")
before = dict(P.fetch_models(realm="cn"))
check("deepseek-v4.1-flash shows the stale x0.03",
      before.get("deepseek-v4.1-flash", {}).get("credits") == "x0.03",
      before.get("deepseek-v4.1-flash", {}).get("credits"))

print()
print("[2] 从上游同步 refreshes list + multipliers")
state = P.sync_models(realm="cn")
check("sync ok", state.get("ok") is True)
after = dict(P.fetch_models(realm="cn"))
check("deepseek-v4.1-flash now shows the live x0.11",
      after.get("deepseek-v4.1-flash", {}).get("credits") == "x0.11 credits",
      after.get("deepseek-v4.1-flash", {}).get("credits"))
glm = P.model_entry("glm-5.2", after["glm-5.2"])
check("glm-5.2 keeps x0.79 and gains the 夜间折扣 badge",
      glm.get("credits", "").startswith("x0.79")
      and glm.get("badges") == [{"text": "夜间折扣", "color": "#1E90FF"}],
      glm.get("badges"))
check("newly discovered upstream models stay hidden under official mode",
      "step-5-preview" not in after and "step-5-preview" in (state.get("hidden") or []),
      state.get("hidden"))

print()
print("[3] panel pool contains hidden live-only models (unhide works)")
cfg = P.models_config_view()["realms"]["cn"]
pool = {m["id"] for m in cfg["pool_models"]}
check("glm-4.7 (hidden, live-only) is in the pool", "glm-4.7" in pool, sorted(pool))
check("glm-4.7 is not in the visible list", "glm-4.7" not in cfg["visible"], cfg["visible"])

print()
print("[4] unhide -> save -> the model shows up with live metadata")
hidden = [h for h in cfg["hidden"] if h != "glm-4.7"]
wb_settings.set_model_config(TMP, "cn", hidden, cfg["order"] + ["glm-4.7"])
P._models_cache["cn"] = {"at": 0.0, "data": None}  # /settings/save clears the cache
restored = dict(P.fetch_models(realm="cn"))
check("glm-4.7 appears in /v1/models", "glm-4.7" in restored)
check("glm-4.7 carries its live credits",
      restored.get("glm-4.7", {}).get("credits") == "x0.23 credits",
      restored.get("glm-4.7", {}).get("credits"))

print()
print("[5] a failed live fetch must not shrink the catalog")
P.fetch_endpoint_models = lambda realm=None, force=False: []
P._models_cache["cn"] = {"at": 0.0, "data": None}
state = P.sync_models(realm="cn")
check("snapshot fallback keeps glm-4.7 discoverable",
      "glm-4.7" in (state.get("discovered") or []), state.get("discovered"))

P.read_product_config_models = _orig_product
P.fetch_endpoint_models = _orig_endpoint
print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
