"""Tests for the unified /v1/models response helper."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_model_registry
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


original_registry = P.unified_model_registry
original_current = P.CURRENT_REALM
try:
    P.CURRENT_REALM = "cn"
    P.unified_model_registry = lambda: wb_model_registry.build_registry({
        "intl": [
            ("shared", {"name": "Shared", "credits": "x0.10"}),
            ("intl-only", {"name": "Global"}),
        ],
        "cn": [
            ("shared", {"name": "Shared CN", "credits": "x0.03"}),
            ("cn-only", {"name": "Domestic"}),
        ],
    })

    print("[1] default model response is the union")
    response = P.models_response()
    ids = [item["id"] for item in response["data"]]
    check("default realm is auto", response["realm"] == "auto", response)
    check("union contains all models", ids == ["shared", "intl-only", "cn-only"], ids)
    shared = next(item for item in response["data"] if item["id"] == "shared")
    check("shared model exposes both realms", shared["x_workbuddy"]["realms"] == ["intl", "cn"], shared)
    check("shared variant metadata survives", shared["x_workbuddy"]["variants"]["cn"]["credits"] == "x0.03", shared)

    print()
    print("[2] realm query filters without using CURRENT_REALM")
    cn_response = P.models_response("cn")
    cn_ids = [item["id"] for item in cn_response["data"]]
    check("cn response labels realm", cn_response["realm"] == "cn", cn_response)
    check("cn response only has cn models", cn_ids == ["shared", "cn-only"], cn_ids)
    check("cn response is independent of current view", "intl-only" not in cn_ids, cn_ids)
finally:
    P.unified_model_registry = original_registry
    P.CURRENT_REALM = original_current

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
