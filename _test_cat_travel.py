"""Regression tests for the current buddy-travel upstream contract."""
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

print("[1] idle travel does not call the retired depart endpoint")
calls = []


def idle_open(req, timeout=0):
    calls.append((req.get_method(), req.full_url))
    return FakeResponse({"code": 0, "data": {"state": "idle", "daily_limit_reached": False}})


try:
    wb_tasks.urllib.request.urlopen = idle_open
    result = wb_tasks.do_cat_travel(account)
finally:
    wb_tasks.urllib.request.urlopen = original_open

check("idle result is successful", result.get("ok") is True, result)
check("idle result reports no reward", result.get("action") == "idle", result)
check("idle did not call depart", all("/travel/depart" not in url for _, url in calls), calls)

print()
print("[2] arrived travel claims the reward")
calls = []


def arrived_open(req, timeout=0):
    calls.append((req.get_method(), req.full_url))
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
      sum(1 for _, url in calls if url.endswith("/travel/claim")) == 1, calls)

print()
print("[3] claim errors preserve the upstream message")


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
