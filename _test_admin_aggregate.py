import tempfile

import wb_proxy
import wb_tenants


def check(name, condition):
    if not condition:
        raise SystemExit("FAIL: " + name)
    print("PASS: " + name)


class FakeAccount:
    def __init__(self, uid):
        self.uid = uid
        self.realm = "cn"
        self.enabled = True
        self.access_token = "token"

    def public(self):
        return {"uid": self.uid}

    def ready(self, model=None):
        return self.enabled and bool(self.access_token)


class FakePool:
    def __init__(self, directory, accounts):
        self.dir = directory
        self.accounts = accounts
        self.removed = []
        self.enabled = []
        self.added = []

    def load(self):
        return self.accounts

    def add(self, account):
        self.added.append(account)
        self.accounts.append(account)
        return account

    def remove(self, uid):
        account = next((item for item in self.accounts if item.uid == uid), None)
        if account is None:
            return False
        self.accounts.remove(account)
        self.removed.append(uid)
        return True

    def set_enabled(self, uid, enabled):
        self.enabled.append((uid, enabled))
        return {"uid": uid, "enabled": enabled}

    def set_all_enabled(self, enabled, realm=None):
        self.enabled.extend((item.uid, enabled) for item in self.accounts)

    def refresh_account(self, account):
        return True

    def import_rows(self, rows, realm=None, overwrite=False):
        return {"added": [], "updated": [], "skipped": [], "invalid": []}

    def preview_import_rows(self, rows, realm=None, overwrite=False):
        return {"added": [], "updated": [], "skipped": [], "invalid": []}

    def start_login(self, realm="intl", platform="CLI"):
        return {"state": "one"}

    def poll_login(self, state):
        return {"status": "pending"}

    def cancel_login(self, state):
        return True

    def import_desktop_credential(self, path, realm=None, source="file"):
        return FakeAccount("desktop")


legacy = FakePool("/global", [FakeAccount("shared"), FakeAccount("global-only")])
first_tenant = FakePool("/tenant-a", [FakeAccount("shared"), FakeAccount("tenant-only")])
second_tenant = FakePool("/tenant-b", [FakeAccount("second-only")])
pool = wb_tenants.AggregateAccountPool([legacy, first_tenant, second_tenant])

check("admin view includes global and tenant accounts",
      {item.uid for item in pool.accounts} == {"shared", "global-only", "tenant-only", "second-only"})
check("admin view de-duplicates shared accounts",
      [item.uid for item in pool.accounts].count("shared") == 1)
check("admin view removes from the owning tenant",
      pool.remove("tenant-only") and first_tenant.removed == ["tenant-only"] and legacy.removed == [])
check("admin view toggles through the owning tenant",
      pool.set_enabled("second-only", False) is not None
      and second_tenant.enabled == [("second-only", False)])
check("admin view still writes new accounts to global",
      pool.add(FakeAccount("new-global")) and legacy.added[-1].uid == "new-global")

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create("aac-admin-view", "wb-admin-view")
    tenant._pool = FakePool("/private-tenant", [FakeAccount("private-account")])
    primary = FakePool("/legacy", [FakeAccount("legacy-account")])
    old_manager = wb_proxy.TENANT_MANAGER
    old_legacy = wb_proxy._LEGACY_POOL
    wb_proxy.TENANT_MANAGER = manager
    wb_proxy._LEGACY_POOL = primary
    try:
        runtime = wb_proxy._admin_aggregate_runtime()
        check("admin request runtime aggregates tenant pools",
              runtime is not None
              and {item.uid for item in runtime.pool.accounts} == {"legacy-account", "private-account"})
    finally:
        wb_proxy.TENANT_MANAGER = old_manager
        wb_proxy._LEGACY_POOL = old_legacy
        wb_proxy._REQUEST_RUNTIME.set(None)
