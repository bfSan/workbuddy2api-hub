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
print("[5] preset aliases are chat-visible and keep their upstream credits")
aliases = dict(P.merge_catalog([
    ("fast-model", {"credits": "x0.21", "name": "快速"}),
    ("balanced-model", {"credits": "x0.65", "name": "均衡"}),
    ("deep-model", {"credits": "x1.20", "name": "极致"}),
], realm="cn"))
for alias in ("fast-model", "balanced-model", "deep-model"):
    check(alias + " present", alias in aliases, sorted(aliases.keys())[:12])
check("preset credits retained", aliases.get("balanced-model", {}).get("credits") == "x0.65")
check("primary-model still excluded", "primary-model" not in aliases)

print()
print("[6] sync hides models that the env filter currently excludes")
sync = P.reconcile_model_sync(
    ["hy3", "deepseek-v4.1-flash", "glm-5.3", "kimi-k3"],
    ["hy3", "deepseek-v4.1-flash", "glm-5.3", "kimi-k3", "fast-model", "internal-hidden"],
    "cn",
)
check("newly discovered alias is visible", "fast-model" in sync["visible"], sync)
check("previously filtered model is hidden", "internal-hidden" in sync["hidden"], sync)
check("currently visible model remains visible", "hy3" in sync["visible"], sync)

print()
print("[7] multiple model sources merge without losing aliases")
merged = dict(P.merge_catalog([
    ("hy3", {"credits": "x9.99"}),
    ("fast-model", {"credits": "x0.21"}),
], realm="cn"))
check("real model and alias coexist", "hy3" in merged and "fast-model" in merged,
      {"hy3": "hy3" in merged, "fast": "fast-model" in merged})

print()
print("[8] endpoint discovery merges rich models and agent presets")
payload = {
    "data": {
        "models": [
            {"id": "hy3", "credits": "x0.10", "name": "HY3"},
            {"id": "glm-5.3", "credits": "x0.20"},
        ],
        "agents": [{
            "models": [
                {"id": "fast-model", "credits": "x0.21", "name": "快速"},
                {"id": "balanced-model", "credits": "x0.65", "name": "均衡"},
                {"id": "deep-model", "credits": "x1.20", "name": "极致"},
            ],
        }],
    },
}
endpoint = dict(P.parse_endpoint_model_payload(payload))
check("rich upstream model retained", endpoint.get("hy3", {}).get("credits") == "x0.10", endpoint.get("hy3"))
check("fast preset retained", endpoint.get("fast-model", {}).get("credits") == "x0.21", endpoint.get("fast-model"))
check("balanced preset retained", endpoint.get("balanced-model", {}).get("credits") == "x0.65", endpoint.get("balanced-model"))
check("deep preset retained", endpoint.get("deep-model", {}).get("credits") == "x1.20", endpoint.get("deep-model"))

print()
print("[9] product cache discovery merges root models and agent presets")
cache = {
    "models": [{"id": "hy3", "credits": "x0.11"}],
    "agents": [{"models": [
        {"id": "fast-model", "credits": "x0.21"},
        {"id": "balanced-model", "credits": "x0.65"},
        {"id": "deep-model", "credits": "x1.20"},
    ]}],
}
cache_models = dict(P.parse_product_config_models(cache))
check("product root model retained", cache_models.get("hy3", {}).get("credits") == "x0.11", cache_models.get("hy3"))
check("product fast preset retained", "fast-model" in cache_models, cache_models)
check("product deep preset retained", "deep-model" in cache_models, cache_models)

print()
print("[10] sync persists filtered models as hidden without exposing them")
wb_settings.set_model_config(TMP, "cn", ["old-hidden"], ["hy3", "fast-model"])
state = P.sync_model_config(
    wb_settings.model_config(TMP),
    "cn",
    [("hy3", {}), ("fast-model", {}), ("balanced-model", {}), ("deep-model", {})],
    [("hy3", {}), ("fast-model", {}), ("balanced-model", {}), ("deep-model", {}), ("internal-only", {})],
)
check("newly discovered preset visible", "balanced-model" in state["visible"], state)
check("filtered model hidden", "internal-only" in state["hidden"], state)
check("previous manual hidden retained", "old-hidden" in state["hidden"], state)
check("order starts with previous order", state["order"][:2] == ["hy3", "fast-model"], state["order"])
persisted = wb_settings.model_config(TMP)["cn"]
check("sync persisted hidden list", "internal-only" in persisted["hidden"], persisted)

print()
print("[11] official-style environment still exposes presets on sync")
wb_settings.set_model_config(TMP, "cn", [], [])
state = P.sync_model_config(
    wb_settings.model_config(TMP),
    "cn",
    [("hy3", {})],
    [("hy3", {}), ("hy3-x", {}), ("fast-model", {}), ("balanced-model", {}), ("deep-model", {})],
)
for alias in ("fast-model", "balanced-model", "deep-model"):
    check(alias + " stays visible", alias in state["visible"], state)
check("non-preset env-filtered model stays hidden", "hy3-x" in state["hidden"], state)

print()
print("[12] saved order can expose a preset through WB_MODEL_SET=official")
os.environ["WB_MODEL_SET"] = "official"
try:
    wb_settings.set_model_config(TMP, "cn", [], ["hy3", "fast-model", "balanced-model", "deep-model"])
    picked = [mid for mid, _ in P.wb_patch_pick(
        P.merge_catalog([
            ("hy3", {}), ("fast-model", {}), ("balanced-model", {}), ("deep-model", {}),
        ], realm="cn"), "cn")]
    for alias in ("fast-model", "balanced-model", "deep-model"):
        check(alias + " passes official filter", alias in picked, picked)
    check("stock model remains", "hy3" in picked, picked)
finally:
    os.environ.pop("WB_MODEL_SET", None)

print()
print("[13] config view exposes full metadata for hidden models")
original_product_reader = P.read_product_config_models
original_endpoint_reader = P.fetch_endpoint_models
try:
    P.read_product_config_models = lambda realm=None: [
        ("hy3", {"credits": "x0.42", "name": "HY3", "supportsToolCall": True}),
        ("hidden-model", {"credits": "x1.23", "name": "Hidden"}),
    ]
    P.fetch_endpoint_models = lambda realm=None, force=False: []
    wb_settings.set_model_config(TMP, "cn", ["hidden-model"], ["hy3", "hidden-model"])
    config = P.models_config_view()
    realm_config = config["realms"]["cn"]
    pool_models = {item["id"]: item for item in realm_config["pool_models"]}
    check("hidden model remains in pool ids", "hidden-model" in realm_config["pool"],
          realm_config["pool"])
    check("hidden model detail keeps credits",
          pool_models.get("hidden-model", {}).get("credits") == "x1.23",
          pool_models.get("hidden-model"))
    check("hidden model is absent from visible list", "hidden-model" not in realm_config["visible"],
          realm_config["visible"])
finally:
    P.read_product_config_models = original_product_reader
    P.fetch_endpoint_models = original_endpoint_reader

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
