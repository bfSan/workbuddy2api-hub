import json
import tempfile

import wb_proxy
import wb_tenants


with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    runtime = manager.get_or_create("aac-json", "wb-json")
    token = wb_proxy._REQUEST_RUNTIME.set(runtime)
    try:
        json.dumps(wb_proxy.runtime_settings_view())
        json.dumps(wb_proxy.usage_snapshot(tenant_id="wb-json"))
        json.dumps({"storage": str(wb_proxy.ACCOUNTS_DIR), "usage": str(wb_proxy.USAGE_DIR)})
    finally:
        wb_proxy._REQUEST_RUNTIME.reset(token)

print("PASS: tenant path views are JSON serializable")
