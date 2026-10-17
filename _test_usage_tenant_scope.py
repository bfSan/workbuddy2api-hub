import tempfile, os, wb_proxy
class P: principal_type='aac-user'; workbuddy_user_id='wb-a'; role='user'
with tempfile.TemporaryDirectory() as td:
    old=wb_proxy.USAGE_LOG; wb_proxy.USAGE_LOG=os.path.join(td,'u.jsonl')
    wb_proxy.record_usage('m', {'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}, tenant_id='wb-a', owner_user_id='wb-a', principal_type='aac-user')
    snap=wb_proxy.usage_snapshot(tenant_id='wb-a', principal=P())
    assert snap['requests']==1
    try: wb_proxy.usage_snapshot(tenant_id='tenant-b', principal=P())
    except Exception: print('PASS: cross tenant usage rejected')
    else: raise SystemExit('FAIL cross tenant usage')
    wb_proxy.USAGE_LOG=old
print('PASS: tenant usage metadata')
import tempfile
with tempfile.TemporaryDirectory() as root:
    manager = __import__('wb_tenants').TenantRuntimeManager(root)
    runtime = manager.get_or_create('aac-auto', 'wb-auto')
    token = wb_proxy._REQUEST_RUNTIME.set(runtime)
    old_log, old_sum = wb_proxy.USAGE_LOG, wb_proxy.USAGE_SUMMARY
    try:
        wb_proxy.USAGE_LOG = os.path.join(root, 'auto.jsonl')
        wb_proxy.USAGE_SUMMARY = os.path.join(root, 'auto-summary.json')
        row = wb_proxy.record_usage('m', {'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})
        assert row['tenant_id'] == 'wb-auto' and row['owner_user_id'] == 'wb-auto'
        print('PASS: request usage auto-scopes tenant')
    finally:
        wb_proxy.USAGE_LOG, wb_proxy.USAGE_SUMMARY = old_log, old_sum
        wb_proxy._REQUEST_RUNTIME.reset(token)
