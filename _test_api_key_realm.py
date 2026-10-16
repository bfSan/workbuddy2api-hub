"""Tests for API Key realm-policy migration to auto."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_settings

PASS = FAIL = 0


def check(label, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


tmp = tempfile.mkdtemp()

print("[1] realm normalization accepts auto and legacy blank values")
check("blank normalizes to auto", wb_settings.normalize_key_realm("") == "auto")
check("auto stays auto", wb_settings.normalize_key_realm("auto") == "auto")
check("invalid value normalizes to auto", wb_settings.normalize_key_realm("other") == "auto")
check("REALMS contains auto", wb_settings.REALMS == ("auto", "intl", "cn"), wb_settings.REALMS)

print()
print("[2] legacy single key is surfaced as auto")
wb_settings.save(tmp, {"api_key_set": True, "api_key": "legacy-key"})
legacy = wb_settings.api_keys(tmp)
check("legacy key is returned", len(legacy) == 1, legacy)
check("legacy key uses auto", legacy[0].get("realm") == "auto", legacy)

print()
print("[3] configured keys normalize and preserve enabled state")
stored = wb_settings.set_api_keys(tmp, [
    {"id": "a", "name": "auto", "key": "key-a", "realm": ""},
    {"id": "i", "name": "intl", "key": "key-i", "realm": "intl"},
    {"id": "c", "name": "cn", "key": "key-c", "realm": "cn", "enabled": False},
])
check("three keys are persisted", len(stored) == 3, stored)
check("blank configured key uses auto", stored[0]["realm"] == "auto", stored)
check("hard intl is retained", stored[1]["realm"] == "intl", stored)
check("disabled cn is retained", stored[2]["realm"] == "cn" and stored[2]["enabled"] is False, stored)
reloaded = wb_settings.api_keys(tmp)
check("reload keeps auto policy", reloaded[0]["realm"] == "auto", reloaded)

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
