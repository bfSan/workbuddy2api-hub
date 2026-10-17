import tempfile
import wb_proxy
import wb_tenants

class Response:
    def __enter__(self): return self
    def __exit__(self, *args): return False

class Account:
    def __init__(self, uid): self.uid=uid; self.realm='intl'; self.enabled=True; self._route_reason=''; self._route_retry_count=0; self._route_failover=False
    def ready(self, model=None): return True
    def headers(self, purpose='chat'): return {}
    def clear_error(self, model=None): pass
    def note_error(self, *args, **kwargs): pass

class Pool:
    def __init__(self, account):
        self.accounts=[account]
        self.affinity=type('A',(),{'get_route':lambda s,k:None,'bind_route':lambda *a:None,'unbind':lambda *a:None})()
    def realm_health(self, model=None, allow=None): return {'intl': True}
    def pick_for_session(self, realm, session_key, exclude, model, allow): return self.accounts[0] if self.accounts[0].uid not in exclude else None

with tempfile.TemporaryDirectory() as root:
    manager=wb_tenants.TenantRuntimeManager(root)
    a=manager.get_or_create('aac-a','wb-a'); b=manager.get_or_create('aac-b','wb-b')
    a._pool=Pool(Account('a-account')); b._pool=Pool(Account('b-account'))
    old_url=wb_proxy.urllib.request.urlopen
    wb_proxy.urllib.request.urlopen=lambda *args, **kwargs: Response()
    try:
        for runtime, expected in ((a,'a-account'),(b,'b-account')):
            token=wb_proxy._REQUEST_RUNTIME.set(runtime)
            try:
                resp, account=wb_proxy.open_upstream({'model':'shared','messages':[{'role':'user','content':'x'}]})
                assert account.uid == expected
            finally:
                wb_proxy._REQUEST_RUNTIME.reset(token)
        print('PASS: open_upstream follows request tenant pool')
    finally:
        wb_proxy.urllib.request.urlopen=old_url
