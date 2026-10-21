import os
import tempfile

import wb_proxy
import wb_settings
import wb_tenants


def check(name, condition):
    if not condition:
        raise SystemExit("FAIL: " + name)
    print("PASS: " + name)


class FakePool:
    accounts = []


with tempfile.TemporaryDirectory() as root:
    global_dir = os.path.join(root, "global")
    tenant_root = os.path.join(root, "tenants")
    os.makedirs(global_dir)
    manager = wb_tenants.TenantRuntimeManager(tenant_root)
    first = manager.get_or_create("aac-first", "wb-first")
    second = manager.get_or_create("aac-second", "wb-second")

    wb_settings.set_api_keys(global_dir, [{
        "id": "k10", "name": "Global", "key": "global-secret",
        "realm": "auto", "enabled": True,
    }])
    wb_settings.set_api_keys(first.root, [{
        "id": "k0", "name": "First tenant", "key": "first-secret",
        "realm": "auto", "enabled": True,
    }])
    wb_settings.set_api_keys(second.root, [{
        "id": "k0", "name": "Second tenant", "key": "second-secret",
        "realm": "auto", "enabled": True,
    }])

    runtime = wb_proxy._AdminAggregateRuntime(
        FakePool(), global_dir, [first, second])
    token = wb_proxy._REQUEST_RUNTIME.set(runtime)
    try:
        entries = wb_proxy.configured_keys()
        check("admin key view includes global and tenant keys", len(entries) == 3)
        check("admin key row ids are unique", len({entry["id"] for entry in entries}) == 3)
        check("admin key view identifies tenant ownership",
              {entry["tenant_id"] for entry in entries} == {"", "aac-first", "aac-second"})
        check("admin key scopes include every key-bearing settings file",
              {(scope["scope"], scope["tenant_id"]) for scope in runtime.api_key_scopes()}
              == {("global", ""), ("tenant", "aac-first"), ("tenant", "aac-second")})
        view = wb_proxy.runtime_settings_view()
        check("settings view exposes aggregated keys and owners",
              len(view["api_keys"]) == 3
              and all(entry.get("owner_label") for entry in view["api_keys"]))
        check("settings view never returns a plaintext key",
              all("key" not in entry for entry in view["api_keys"]))

        rows = []
        for entry in entries:
            row = dict(entry)
            row["key"] = ""
            if entry["tenant_id"] == "aac-first":
                row["name"] = "First tenant renamed"
            rows.append(row)
        saved = wb_proxy._save_admin_api_keys(
            runtime, rows, runtime.api_key_scopes())
        check("admin save keeps all keys", saved == 3)
        check("admin save writes tenant changes to its owner",
              wb_settings.api_keys(first.root)[0]["name"] == "First tenant renamed")
        check("admin save preserves tenant secret",
              wb_settings.api_keys(first.root)[0]["key"] == "first-secret")
        check("admin save does not copy tenant key into global",
              len(wb_settings.api_keys(global_dir)) == 1)

        remaining = [
            dict(entry, key="")
            for entry in runtime.api_keys()
            if entry["tenant_id"] != "aac-first"
        ]
        wb_proxy._save_admin_api_keys(
            runtime, remaining, runtime.api_key_scopes())
        check("admin can remove a tenant key from its owner",
              wb_settings.api_keys(first.root) == [])
        check("removing one tenant key leaves another tenant untouched",
              wb_settings.api_keys(second.root)[0]["key"] == "second-secret")
    finally:
        wb_proxy._REQUEST_RUNTIME.reset(token)

print("PASS: admin api key aggregation")
