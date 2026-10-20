"""Regression tests for panel-managed gateway key status reporting."""
import tempfile

import wb_proxy as P
import wb_settings


tmp = tempfile.mkdtemp()
P.ACCOUNTS_DIR = tmp
P.API_KEY = None
wb_settings.set_api_keys(tmp, [{"id": "panel", "name": "Panel", "key": "panel-key", "enabled": True}])

assert P.api_key_configured() is True
assert P.auth_required() is True
assert P.runtime_settings_view()["api_key_set"] is True

wb_settings.set_api_keys(tmp, [{"id": "panel", "name": "Panel", "key": "panel-key", "enabled": False}])
assert P.api_key_configured() is True
assert P.auth_required() is False

print("PASS: panel-managed API key status is reflected without launcher API_KEY")
