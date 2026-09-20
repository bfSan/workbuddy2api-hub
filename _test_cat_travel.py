"""Regression tests for the buddy-travel upstream contract."""
import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_tasks

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


class DummyAccount(object):
    uid = "test-user"
    access_token = "token"

    def headers(self, purpose="chat"):
        return {"Authorization": "Bearer token"}

    def fetch_credits(self):
        return True


class FakeResponse(object):
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


account = DummyAccount()
original_open = wb_tasks.urllib.request.urlopen

print("[1] idle travel dispatches the buddy to a configured location")
calls = []


def idle_open(req, timeout=0):
    calls.append((req.get_method(), req.full_url, req.data))
    if req.full_url.endswith("/travel/status"):
        return FakeResponse({"code": 0, "data": {"state": "idle", "daily_limit_reached": False}})
    if req.full_url.endswith("/travel/config"):
        return FakeResponse({
            "code": 0,
            "data": {
                "locations": [
                    {"id": 17, "name": "杭州", "duration_hours_min": 1, "duration_hours_max": 4},
                ]
            },
        })
    if req.full_url.endswith("/travel/depart"):
        check("depart sends location_id from config",
              json.loads(req.data.decode("utf-8")) == {"location_id": 17}, req.data)
        return FakeResponse({
            "code": 0,
            "data": {"state": "traveling", "location": {"id": 17, "name": "杭州"}},
        })
    raise AssertionError("unexpected URL: " + req.full_url)


try:
    wb_tasks.urllib.request.urlopen = idle_open
    result = wb_tasks.do_cat_travel(account)
finally:
    wb_tasks.urllib.request.urlopen = original_open

check("idle result is successful", result.get("ok") is True, result)
check("idle result reports depart", result.get("action") == "depart", result)
check("idle fetches config then departs",
      [url.rsplit("/", 1)[-1] for _, url, _ in calls] == ["status", "config", "depart"], calls)

print()
print("[2] daily-limit idle travel does not dispatch")
calls = []


def limited_open(req, timeout=0):
    calls.append((req.get_method(), req.full_url, req.data))
    if req.full_url.endswith("/travel/status"):
        return FakeResponse({"code": 0, "data": {"state": "idle", "daily_limit_reached": True}})
    raise AssertionError("unexpected URL: " + req.full_url)


try:
    wb_tasks.urllib.request.urlopen = limited_open
    result = wb_tasks.do_cat_travel(account)
finally:
    wb_tasks.urllib.request.urlopen = original_open

check("limited idle result is successful", result.get("ok") is True, result)
check("limited idle reports idle", result.get("action") == "idle", result)
check("limited idle does not fetch config or depart",
      [url.rsplit("/", 1)[-1] for _, url, _ in calls] == ["status"], calls)

print()
print("[3] arrived travel claims the reward")
calls = []


def arrived_open(req, timeout=0):
    calls.append((req.get_method(), req.full_url, req.data))
    if req.full_url.endswith("/travel/status"):
        return FakeResponse({"code": 0, "data": {"state": "arrived", "reward_credit": 88}})
    if req.full_url.endswith("/travel/claim"):
        return FakeResponse({"code": 0, "data": {"reward_credit": 88}})
    raise AssertionError("unexpected URL: " + req.full_url)


try:
    wb_tasks.urllib.request.urlopen = arrived_open
    result = wb_tasks.do_cat_travel(account)
finally:
    wb_tasks.urllib.request.urlopen = original_open

check("arrived result is successful", result.get("ok") is True, result)
check("arrived reward is returned", result.get("credit") == 88, result)
check("arrived calls claim exactly once",
      sum(1 for _, url, _ in calls if url.endswith("/travel/claim")) == 1, calls)

print()
print("[4] depart errors preserve the upstream message")


def depart_error_open(req, timeout=0):
    if req.full_url.endswith("/travel/status"):
        return FakeResponse({"code": 0, "data": {"state": "idle", "daily_limit_reached": False}})
    if req.full_url.endswith("/travel/config"):
        return FakeResponse({"code": 0, "data": {"locations": [{"id": 23, "name": "成都"}]}})
    if req.full_url.endswith("/travel/depart"):
        body = io.BytesIO(json.dumps({"code": 400, "msg": "location not available"}).encode("utf-8"))
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, body)
    raise AssertionError("unexpected URL: " + req.full_url)


try:
    wb_tasks.urllib.request.urlopen = depart_error_open
    result = wb_tasks.do_cat_travel(account)
finally:
    wb_tasks.urllib.request.urlopen = original_open

check("depart error is surfaced", "location not available" in result.get("msg", ""), result)

print()
print("[5] claim errors preserve the upstream message")


def claim_error_open(req, timeout=0):
    if req.full_url.endswith("/travel/status"):
        return FakeResponse({"code": 0, "data": {"state": "arrived"}})
    body = io.BytesIO(json.dumps({"code": 400, "msg": "no unclaimed travel"}).encode("utf-8"))
    raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, body)


try:
    wb_tasks.urllib.request.urlopen = claim_error_open
    result = wb_tasks.do_cat_travel(account)
finally:
    wb_tasks.urllib.request.urlopen = original_open

check("claim error is surfaced", "no unclaimed travel" in result.get("msg", ""), result)

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
