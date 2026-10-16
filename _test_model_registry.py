"""Tests for the merged domestic/international model registry."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_model_registry

PASS = FAIL = 0


def check(label, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


entries = {
    "intl": [
        ("shared", {"name": "Shared", "credits": "x0.10", "supportsImages": True}),
        ("intl-only", {"name": "Global", "credits": "x1.00"}),
        # A later live entry wins over an earlier cached/static entry.
        ("shared", {"name": "Shared", "credits": "x0.08", "live": True}),
    ],
    "cn": [
        ("shared", {"name": "Shared CN", "credits": "x0.03", "supportsToolCall": True}),
        ("cn-only", {"name": "Domestic", "credits": "x0.20"}),
    ],
}

print("[1] registry keeps one record per model and both regional variants")
registry = wb_model_registry.build_registry(entries)
check("shared model exists once", list(registry).count("shared") == 1, registry)
check("shared model exposes both realms", registry["shared"]["realms"] == ("intl", "cn"), registry["shared"])
check("intl-only model exposes intl", registry["intl-only"]["realms"] == ("intl",), registry["intl-only"])
check("cn-only model exposes cn", registry["cn-only"]["realms"] == ("cn",), registry["cn-only"])
check("live entry wins in one realm", registry["shared"]["variants"]["intl"]["live"] is True,
      registry["shared"])
check("regional metadata is retained", registry["shared"]["variants"]["cn"]["supportsToolCall"] is True,
      registry["shared"])

print()
print("[2] realm lookup and merged public entries are deterministic")
check("shared realm lookup is ordered", wb_model_registry.model_realms(registry, "shared") == ("intl", "cn"))
check("unknown model has no realms", wb_model_registry.model_realms(registry, "missing") == ())
merged = dict(wb_model_registry.merged_entries(registry))
check("merged entry keeps display metadata", merged["shared"]["name"] == "Shared", merged["shared"])
check("merged entry exposes realms", merged["shared"]["x_workbuddy"]["realms"] == ["intl", "cn"], merged["shared"])
check("merged entry exposes variant credits",
      merged["shared"]["x_workbuddy"]["variants"]["cn"]["credits"] == "x0.03",
      merged["shared"])

print()
print("[3] public ordering follows intl then cn input order")
ids = [mid for mid, _meta in wb_model_registry.merged_entries(registry)]
check("ordering is stable", ids == ["shared", "intl-only", "cn-only"], ids)

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
