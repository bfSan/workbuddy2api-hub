import wb_settings

def check(name, condition):
    if not condition: raise SystemExit("FAIL: "+name)
    print("PASS: "+name)
user=type("P",(),{"principal_type":"aac-user","workbuddy_user_id":"a","role":"user"})()
admin=type("P",(),{"principal_type":"aac-user","workbuddy_user_id":"a","role":"admin"})()
local=type("P",(),{"principal_type":"local-admin","workbuddy_user_id":"","role":"admin"})()
wb_settings.authorize_route(user,"accounts","GET",resource_owner_id="a")
check("user own route allowed",True)
try: wb_settings.authorize_route(user,"accounts","GET",resource_owner_id="b")
except wb_settings.AuthzError: check("user cross tenant denied",True)
else: check("user cross tenant denied",False)
wb_settings.authorize_route(admin,"accounts","GET",resource_owner_id="b")
check("admin app scope allowed",True)
wb_settings.authorize_route(local,"settings","POST")
check("local admin compatibility",True)
wb_settings.authorize_route(user,"tasks","POST",resource_owner_id="a")
check("user own tasks allowed",True)
try: wb_settings.authorize_route(user,"scheduler","POST")
except wb_settings.AuthzError: check("user scheduler denied",True)
else: check("user scheduler denied",False)

# A browser may retain a local panel session while the user signs in through
# AAC. The AAC identity must win so an ordinary user cannot inherit the global
# account pool from that stale panel token.
import tempfile
import wb_auth
import wb_proxy
import wb_tenants

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create("aac-user", "aac-user")
    oauth = wb_auth.create_oauth_session({
        "sub": "aac-user", "aud": "workbuddy2api-hub",
        "client_id": "workbuddy2api-hub", "grants": ["workbuddy:access"],
    })
    panel = wb_auth.create_local_admin_session({"session_id": "stale-panel"})
    old_manager = wb_proxy.TENANT_MANAGER
    wb_proxy.TENANT_MANAGER = manager
    handler = wb_proxy.Handler.__new__(wb_proxy.Handler)
    handler.headers = {
        "Cookie": "WB-Session=%s; WB-Panel-Session=%s" % (oauth["session_id"], panel["session_id"]),
        "X-Panel-Token": "stale-panel",
    }
    handler.key_entry = None
    handler.principal = None
    handler.tenant_runtime = None
    handler._panel_ok = lambda: True
    handler._supplied_key = lambda: ""
    try:
        check("AAC user wins over stale panel session", handler._key_ok())
        check("AAC user keeps tenant scope", handler.principal.role == "user" and handler.tenant_runtime is tenant)
        check("stale panel cannot unlock management", handler._management_ok() is False)
        check("tenant runtime selected", handler.tenant_runtime is tenant)
    finally:
        wb_proxy.TENANT_MANAGER = old_manager
        wb_proxy._REQUEST_RUNTIME.set(None)
