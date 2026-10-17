import wb_scheduler
class T: root='x'; workbuddy_user_id='wb-a'
class P: accounts=[]
s=wb_scheduler.InstanceScheduler()
assert s.register_tenant(T()) == 'wb-a'
print('PASS: scheduler tenant registration')
try: wb_scheduler.TenantScheduler().run_once(T(),'wb-b',{})
except wb_scheduler.SchedulerError as e: print('PASS: cross tenant task rejected')

import wb_proxy, tempfile, wb_tenants
with tempfile.TemporaryDirectory() as root:
    manager = wb_tenants.TenantRuntimeManager(root)
    runtime = manager.get_or_create('aac-s', 'wb-s')
    class FakeScheduler:
        enabled = True
        def status(self): return {'owner': 'wb-s'}
    runtime._scheduler = FakeScheduler()
    token = wb_proxy._REQUEST_RUNTIME.set(runtime)
    try:
        assert wb_proxy.TENANT_SCHEDULER.status()['owner'] == 'wb-s'
        print('PASS: scheduler proxy follows request tenant')
    finally:
        wb_proxy._REQUEST_RUNTIME.reset(token)
