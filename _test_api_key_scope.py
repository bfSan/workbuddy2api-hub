import os, tempfile, time
import wb_settings
import wb_tenants

def check(name, condition):
    if not condition: raise SystemExit("FAIL: "+name)
    print("PASS: "+name)
with tempfile.TemporaryDirectory() as td:
    issued=wb_settings.issue_user_api_key(td,"wb-a","test")
    check("key plaintext returned once", bool(issued.get("credential")) and "credential" not in issued["metadata"])
    check("correct app resolves", wb_settings.resolve_api_key(issued["credential"],"workbuddy2api-hub",tenant_dir=td).owner_user_id == "wb-a")
    check("wrong app rejected", wb_settings.resolve_api_key(issued["credential"],"qoder2api-hub",tenant_dir=td) is None)
    check("expired key rejected", wb_settings.resolve_api_key(issued["credential"],"workbuddy2api-hub",tenant_dir=td,now=time.time()+10**9) is None)

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create('aac-a', 'wb-a')
    issued = wb_settings.issue_user_api_key(tenant.root, 'wb-a', 'indexed')
    resolved = manager.resolve_api_key_tenant(issued['credential'])
    check('api key resolves tenant without session', resolved is not None and resolved.workbuddy_user_id == 'wb-a')
    check('unknown api key fails closed', manager.resolve_api_key_tenant('wbk_unknown') is None)

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    a = manager.get_or_create('aac-a', 'wb-a')
    b = manager.get_or_create('aac-b', 'wb-b')
    issued = wb_settings.issue_user_api_key(a.root, 'wb-a', 'duplicate')
    manager.register_api_key_owner(issued['credential'], a)
    try:
        manager.register_api_key_owner(issued['credential'], b)
    except wb_tenants.TenantError as exc:
        check('duplicate key owner fails closed', exc.code == 'WB_API_KEY_OWNER_CONFLICT')
    else:
        check('duplicate key owner fails closed', False)

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create('aac-issued', 'wb-issued')
    issued = manager.issue_api_key(tenant, 'managed')
    check('manager-issued key is indexed', manager.resolve_api_key_tenant(issued['credential']).workbuddy_user_id == 'wb-issued')

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create('aac-panel-key', 'wb-panel-key')
    wb_settings.set_api_keys(tenant.root, [{
        'id': 'panel', 'name': 'Panel key', 'key': 'wbk_panel_managed',
        'enabled': True,
    }])
    resolved = manager.resolve_api_key_tenant('wbk_panel_managed')
    check('panel-managed tenant key resolves without a session',
          resolved is not None and resolved.workbuddy_user_id == 'wb-panel-key')

with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    first = manager.get_or_create('aac-panel-a', 'wb-panel-a')
    second = manager.get_or_create('aac-panel-b', 'wb-panel-b')
    duplicate = [{'id': 'panel', 'name': 'Duplicate', 'key': 'wbk_duplicate', 'enabled': True}]
    wb_settings.set_api_keys(first.root, duplicate)
    wb_settings.set_api_keys(second.root, duplicate)
    check('ambiguous tenant panel key fails closed',
          manager.resolve_api_key_tenant('wbk_duplicate') is None)

with tempfile.TemporaryDirectory() as root:
    import wb_proxy
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create('aac-handler', 'wb-handler')
    issued = manager.issue_api_key(tenant, 'handler')
    old_manager = wb_proxy.TENANT_MANAGER
    wb_proxy.TENANT_MANAGER = manager
    handler = wb_proxy.Handler.__new__(wb_proxy.Handler)
    handler.key_entry = None; handler.principal = None; handler.tenant_runtime = None
    handler._panel_ok = lambda: False
    handler._supplied_key = lambda: issued['credential']
    handler.headers = {}
    try:
        check('handler resolves standalone key tenant', handler._key_ok() and handler.tenant_runtime.workbuddy_user_id == 'wb-handler')
        check('handler key uses tenant pool', wb_proxy.POOL.accounts is tenant.pool.accounts)
    finally:
        wb_proxy.TENANT_MANAGER = old_manager
        wb_proxy._REQUEST_RUNTIME.set(None)

with tempfile.TemporaryDirectory() as root:
    import wb_proxy
    manager = wb_tenants.TenantRuntimeManager(root)
    tenant = manager.get_or_create('aac-panel-handler', 'wb-panel-handler')
    wb_settings.set_api_keys(tenant.root, [{
        'id': 'panel', 'name': 'Handler key', 'key': 'wbk_handler_panel',
        'enabled': True,
    }])
    old_manager = wb_proxy.TENANT_MANAGER
    wb_proxy.TENANT_MANAGER = manager
    handler = wb_proxy.Handler.__new__(wb_proxy.Handler)
    handler.key_entry = None; handler.principal = None; handler.tenant_runtime = None
    handler._panel_ok = lambda: False
    handler._supplied_key = lambda: 'wbk_handler_panel'
    handler.headers = {}
    try:
        check('handler accepts panel-managed tenant key',
              handler._key_ok() and handler.tenant_runtime.workbuddy_user_id == 'wb-panel-handler')
        check('handler keeps the panel key identity',
              handler.key_entry is not None and handler.key_entry.get('id') == 'panel')
    finally:
        wb_proxy.TENANT_MANAGER = old_manager
        wb_proxy._REQUEST_RUNTIME.set(None)
