import wb_auth

def check(name, condition):
    if not condition:
        raise SystemExit("FAIL: %s" % name)
    print("PASS: %s" % name)

local = wb_auth.create_local_admin_session({"session_id": "local-1"})
principal = wb_auth.resolve_principal({}, {"WB-Panel-Session": local["session_id"]}, {}, local_sessions={local["session_id"]: local})
check("local admin preserved", principal.principal_type == "local-admin")
check("local admin auth method", principal.auth_method == "local-panel")
check("local admin has no AAC identity", principal.aac_user_id == "")
