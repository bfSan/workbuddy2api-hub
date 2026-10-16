"""Regression checks for the unified domestic/international management view."""

import json
import os
import tempfile

import wb_proxy as P
import wb_settings


def check(name, condition, detail=None):
    if not condition:
        raise SystemExit("FAIL: %s%s" % (name, (" -> %r" % detail) if detail is not None else ""))
    print("PASS: %s" % name)


print("[1] usage helpers treat omitted realm as the merged data set")
old_pool = P.POOL
old_log = P.USAGE_LOG
old_current = P.CURRENT_REALM
try:
    class Account:
        def __init__(self, uid, realm):
            self.uid = uid
            self.realm = realm
            self.nickname = uid
            self.access_token = "token"
            self.domain = "www.workbuddy.ai" if realm == "intl" else "copilot.tencent.com"
            self.enabled = True
            self.path = ""
            self.expires_at = 0

    class Pool:
        accounts = [Account("i1", "intl"), Account("c1", "cn")]
        def representative(self, realm=None):
            return self.accounts[0] if realm in (None, "intl") else self.accounts[1]
        def count_ready(self, realm=None):
            return len(self.accounts) if realm is None else 1

    P.POOL = Pool()
    P.CURRENT_REALM = "cn"
    with tempfile.TemporaryDirectory() as td:
        P.USAGE_LOG = os.path.join(td, "usage.jsonl")
        rows = [
            {"model": "intl-model", "realm": "intl", "account": "i1", "total_tokens": 2},
            {"model": "cn-model", "realm": "cn", "account": "c1", "total_tokens": 3},
        ]
        with open(P.USAGE_LOG, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        P._snap_cache.clear()
        merged = P.usage_snapshot()
        recent = P.recent_usage(10)
        check("usage snapshot is auto", merged.get("realm") == "auto", merged)
        check("usage snapshot contains both regions", merged.get("requests") == 2, merged)
        check("recent usage contains both regions", len(recent.get("rows") or []) == 2, recent)
finally:
    P.POOL = old_pool
    P.USAGE_LOG = old_log
    P.CURRENT_REALM = old_current


print("[2] model sync without a realm refreshes both catalogs")
old_sync_one = getattr(P, "_sync_models_one", None)
calls = []
try:
    def fake_sync_one(realm):
        calls.append(realm)
        return {"ok": True, "realm": realm, "discovered": [realm + "-model"]}
    P._sync_models_one = fake_sync_one
    result = P.sync_models()
    check("sync calls intl and cn", calls == ["intl", "cn"], calls)
    check("sync reports auto", result.get("realm") == "auto", result)
finally:
    if old_sync_one is None:
        delattr(P, "_sync_models_one")
    else:
        P._sync_models_one = old_sync_one


print("[3] panel API key saves always use automatic routing")
check("panel normalizer exists", hasattr(P, "normalize_panel_key_realm"))
check("panel normalizer returns auto", P.normalize_panel_key_realm("intl") == "auto")
check("panel normalizer returns auto for blank", P.normalize_panel_key_realm("") == "auto")


print("[4] dashboard uses one merged management view")
with open("dashboard.html", encoding="utf-8") as fh:
    dashboard = fh.read()
check("no realm tabs", "id=\"tabIntl\"" not in dashboard and "id=\"tabCn\"" not in dashboard)
check("no manual gateway toggle", "toggleActiveGatewayRealm" not in dashboard)
check("accounts request merged data", "getJSON('/accounts?realm='" not in dashboard)
check("models request merged data", "getJSON('/v1/models?realm='" not in dashboard)
check("usage request merged data", "getJSON('/usage?realm='" not in dashboard)
check("models render realm field", "modelRealmBadges" in dashboard)
check("key UI has no fixed realm choices", "固定国际版出口" not in dashboard and "固定国内版出口" not in dashboard)

print("ALL PASS")
