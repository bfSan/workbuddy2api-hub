import os
import tempfile
import wb_tenants


def check(name, condition):
    if not condition: raise SystemExit("FAIL: " + name)
    print("PASS: " + name)

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    a = manager.get_or_create("aac-a", "wb-a")
    b = manager.get_or_create("aac-b", "wb-b")
    check("tenant paths are disjoint", a.root != b.root and "aac-a" in a.root and "aac-b" in b.root)
    check("tenant root private", (os.stat(a.root).st_mode & 0o777) == 0o700)
    a.settings.save({"app_id": "workbuddy2api-hub", "owner_user_id": "wb-a", "value": 1})
    check("tenant settings are isolated", b.settings.load() == {})
    try:
        manager.get_or_create("../escape", "wb-x")
    except ValueError:
        check("path traversal rejected", True)
    else:
        check("path traversal rejected", False)
    try:
        manager.assert_owner("wb-b", type("P", (), {"workbuddy_user_id": "wb-a", "principal_type": "aac-user"})())
    except wb_tenants.TenantError as exc:
        check("cross tenant denied", exc.code == "WB_TENANT_FORBIDDEN")
    else:
        check("cross tenant denied", False)
