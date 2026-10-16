"""Tests for account-selected cross-realm upstream execution."""
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_proxy as P

PASS = FAIL = 0


def check(label, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


class FakeAccount:
    def __init__(self, uid, realm):
        self.uid = uid
        self.realm = realm
        self.access_token = "token-" + uid
        self.cooldown_until = 0
        self.model_cooldowns = {}
        self.errors = []

    def ready(self, model=None):
        return self.cooldown_until <= 0 and not self.model_cooldowns.get(model)

    def headers(self, purpose="chat"):
        return {
            "Authorization": "Bearer " + self.access_token,
            "X-User-Id": self.uid,
        }

    def clear_error(self, model=None):
        self.cooldown_until = 0
        self.model_cooldowns.pop(model, None)

    def note_error(self, message, cooldown=300, single_account=False, model=None, account_wide=True):
        self.errors.append((message, model, account_wide))
        if account_wide:
            self.cooldown_until = 1
        elif model:
            self.model_cooldowns[model] = 1


class FakePool:
    def __init__(self, accounts):
        self.accounts = accounts
        self._cursor = 0
        import wb_accounts
        self.affinity = wb_accounts.SessionAffinity()

    def realm_health(self, model=None, allow=None):
        allow = set(allow) if allow is not None else None
        out = {}
        for account in self.accounts:
            if account.realm in ("intl", "cn") and (allow is None or account.uid in allow):
                if account.ready(model):
                    out[account.realm] = out.get(account.realm, 0) + 1
        return out

    def pick_for_session(self, realm=None, session_key=None, exclude=None, model=None, allow=None):
        exclude = set(exclude or ())
        allow = set(allow) if allow is not None else None
        bound = self.affinity.get_route(session_key) if session_key else None
        if bound and bound.get("realm") == realm and bound.get("uid") not in exclude:
            for account in self.accounts:
                if account.uid == bound.get("uid") and account.ready(model):
                    return account
        for account in self.accounts:
            if account.uid in exclude or account.realm != realm:
                continue
            if allow is not None and account.uid not in allow:
                continue
            if account.ready(model):
                return account
        return None


class FakeResponse:
    pass


original_pool = P.POOL
original_urlopen = P.urllib.request.urlopen
original_registry = P.unified_model_registry
original_current = P.CURRENT_REALM
calls = []
failed_uids = set()


def fake_urlopen(req, timeout=None):
    uid = req.get_header("X-user-id")
    calls.append((uid, req.full_url))
    if uid == "cn-1" and uid not in failed_uids:
        failed_uids.add(uid)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
    return FakeResponse()


try:
    intl = FakeAccount("intl-1", "intl")
    cn = FakeAccount("cn-1", "cn")
    P.POOL = FakePool([cn, intl])
    P.CURRENT_REALM = "cn"
    P.unified_model_registry = lambda: {
        "shared": {"realms": ("intl", "cn")},
        "gpt-6-astra": {"realms": ("intl",)},
    }
    P.urllib.request.urlopen = fake_urlopen

    print("[1] shared model follows account affinity, not CURRENT_REALM")
    P.POOL.affinity.bind_route("session", "intl", "intl-1")
    response, selected = P.open_upstream(
        {"model": "shared", "messages": [{"role": "user", "content": "hi"}]},
        session_key="session", key_realm="auto",
    )
    check("affinity selects intl account", selected.uid == "intl-1", selected.uid)
    check("selected URL is international", calls[-1][1].startswith("https://www.workbuddy.ai/"), calls[-1])

    print()
    print("[2] exclusive model rejects incompatible hard policy before network")
    before = len(calls)
    try:
        P.open_upstream(
            {"model": "gpt-6-astra", "messages": [{"role": "user", "content": "hi"}]},
            key_realm="cn",
        )
    except ValueError as exc:
        check("hard cn policy rejected", "unavailable in cn" in str(exc), exc)
    else:
        check("hard cn policy rejected", False, "no error")
    check("incompatible policy made no call", len(calls) == before, calls)

    print()
    print("[3] 429 fails over from domestic to international")
    P.POOL.affinity.bind_route("failover", "cn", "cn-1")
    before = len(calls)
    response, selected = P.open_upstream(
        {"model": "shared", "messages": [{"role": "user", "content": "retry"}]},
        session_key="failover", key_realm="auto",
    )
    check("failover selects intl account", selected.uid == "intl-1", selected.uid)
    check("two calls were made", len(calls) == before + 2, calls)
    check("first call was domestic", calls[-2][1].startswith("https://copilot.tencent.com/"), calls[-2])
    check("second call was international", calls[-1][1].startswith("https://www.workbuddy.ai/"), calls[-1])
finally:
    P.POOL = original_pool
    P.urllib.request.urlopen = original_urlopen
    P.unified_model_registry = original_registry
    P.CURRENT_REALM = original_current

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
