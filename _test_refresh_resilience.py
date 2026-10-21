import base64
import json
import os
import tempfile

import wb_accounts
import wb_proxy


def check(name, condition):
    if not condition:
        raise SystemExit("FAIL: " + name)
    print("PASS: " + name)


def token(uid, exp=4102444800):
    def encode(value):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return ".".join((
        encode({"alg": "none"}),
        encode({
            "iss": "https://copilot.tencent.com/v2/plugin/auth",
            "sub": uid,
            "aud": "workbuddy",
            "exp": exp,
        }),
        "signature",
    ))


with tempfile.TemporaryDirectory() as root:
    account = wb_accounts.Account({
        "uid": "refresh-account",
        "domain": "copilot.tencent.com",
        "accessToken": token("refresh-account", 1),
        "refreshToken": "old-refresh",
    }, path=os.path.join(root, "refresh-account.json"))

    original_http_json = wb_accounts.http_json
    original_save = account.save
    wb_accounts.http_json = lambda *args, **kwargs: {
        "data": {
            "accessToken": token("refresh-account"),
            "refreshToken": "new-refresh",
            "domain": "copilot.tencent.com",
        }
    }

    def denied_save(directory):
        raise PermissionError("read-only volume")

    account.save = denied_save
    try:
        ok = account.refresh()
    finally:
        wb_accounts.http_json = original_http_json
        account.save = original_save

    check("refresh reports a persistence failure instead of raising",
          ok is False and "could not be saved" in account.last_error)


class FailingPool:
    def __init__(self, account):
        self.account = account

    def get(self, uid):
        return self.account if uid == self.account.uid else None

    def refresh_account(self, account):
        raise PermissionError("read-only volume")


class DummyHandler:
    def __init__(self):
        self.reply = None

    def _json(self, status, payload):
        self.reply = (status, payload)
        return payload


original_pool = wb_proxy.POOL
try:
    wb_proxy.POOL = FailingPool(account)
    handler = DummyHandler()
    wb_proxy.Handler._handle_accounts(
        handler,
        "/accounts/refresh",
        {"uid": account.uid},
    )
finally:
    wb_proxy.POOL = original_pool

result = handler.reply[1]["results"][0]
check("refresh endpoint returns a structured result on write failure",
      handler.reply[0] == 200 and result["ok"] is False
      and "read-only volume" in result["error"])
