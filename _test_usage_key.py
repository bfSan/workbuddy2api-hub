"""Tests for API-key usage aggregation."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TMP = tempfile.mkdtemp()
LOG = os.path.join(TMP, "usage.jsonl")

import wb_proxy as P

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


rows = [
    {"model": "hy3", "key_id": "k1", "key_name": "alpha", "account": "a1",
     "prompt_tokens": 10, "completion_tokens": 5, "reasoning_tokens": 2,
     "cached_tokens": 3, "total_tokens": 15, "credit": 0.5,
     "ttft_ms": 100, "elapsed_ms": 500, "tokens_per_sec": 50},
    {"model": "hy3", "key_id": "k1", "key_name": "alpha", "account": "a1",
     "error": True, "status": 429},
    {"model": "hy4-preview", "account": "a2", "total_tokens": 999},
]
with open(LOG, "w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row) + "\n")

result = P.usage_by_key(log_path=LOG, configured=[
    {"id": "k1", "name": "alpha", "enabled": True},
    {"id": "k2", "name": "beta", "enabled": True},
])
by_id = {row["key_id"]: row for row in result}
check("unkeyed historical row is excluded", "(埋点前)" not in by_id and len(result) == 2, result)
check("configured empty key is present", "k2" in by_id, result)
check("successful requests counted", by_id["k1"]["requests"] == 1, by_id["k1"])
check("errors counted", by_id["k1"]["errors"] == 1, by_id["k1"])
check("reasoning tokens retained", by_id["k1"]["reasoning_tokens"] == 2, by_id["k1"])
check("cached tokens retained", by_id["k1"]["cached_tokens"] == 3, by_id["k1"])
check("success rate exposed", by_id["k1"]["success_rate_pct"] == 50.0, by_id["k1"])
check("cache hit rate exposed", by_id["k1"]["cache_hit_pct"] == 30.0, by_id["k1"])

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
