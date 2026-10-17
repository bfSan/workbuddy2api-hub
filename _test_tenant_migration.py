import json, os, tempfile
import wb_tenants

def check(name, condition):
    if not condition: raise SystemExit("FAIL: " + name)
    print("PASS: " + name)
with tempfile.TemporaryDirectory() as root:
    source=os.path.join(root,"legacy"); target=os.path.join(root,"tenants","wb-a")
    os.makedirs(source)
    with open(os.path.join(source,"acct.json"),"w") as f: json.dump({"token":"secret"},f)
    result=wb_tenants.migrate_legacy_accounts(source,target,"wb-a",dry_run=True)
    check("dry run counts", result["files"] == 1 and not os.path.exists(target))
    result=wb_tenants.migrate_legacy_accounts(source,target,"wb-a")
    check("migration copies file", os.path.exists(os.path.join(target,"acct.json")))
    try: wb_tenants.migrate_legacy_accounts(source,target,"wb-a")
    except wb_tenants.TenantError as exc: check("migration refuses overwrite", exc.code == "WB_TENANT_TARGET_EXISTS")
    else: check("migration refuses overwrite", False)
