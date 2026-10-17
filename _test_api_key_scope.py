import os, tempfile, time
import wb_settings

def check(name, condition):
    if not condition: raise SystemExit("FAIL: "+name)
    print("PASS: "+name)
with tempfile.TemporaryDirectory() as td:
    issued=wb_settings.issue_user_api_key(td,"wb-a","test")
    check("key plaintext returned once", bool(issued.get("credential")) and "credential" not in issued["metadata"])
    check("correct app resolves", wb_settings.resolve_api_key(issued["credential"],"workbuddy2api-hub",tenant_dir=td).owner_user_id == "wb-a")
    check("wrong app rejected", wb_settings.resolve_api_key(issued["credential"],"qoder2api-hub",tenant_dir=td) is None)
    check("expired key rejected", wb_settings.resolve_api_key(issued["credential"],"workbuddy2api-hub",tenant_dir=td,now=time.time()+10**9) is None)
