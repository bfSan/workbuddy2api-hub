import wb_scheduler
class T: root='x'; workbuddy_user_id='wb-a'
class P: accounts=[]
s=wb_scheduler.InstanceScheduler()
assert s.register_tenant(T()) == 'wb-a'
print('PASS: scheduler tenant registration')
try: wb_scheduler.TenantScheduler().run_once(T(),'wb-b',{})
except wb_scheduler.SchedulerError as e: print('PASS: cross tenant task rejected')
