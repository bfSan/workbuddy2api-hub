import wb_settings

def check(name, condition):
    if not condition: raise SystemExit("FAIL: "+name)
    print("PASS: "+name)
user=type("P",(),{"principal_type":"aac-user","workbuddy_user_id":"a","role":"user"})()
admin=type("P",(),{"principal_type":"aac-user","workbuddy_user_id":"a","role":"admin"})()
local=type("P",(),{"principal_type":"local-admin","workbuddy_user_id":"","role":"admin"})()
wb_settings.authorize_route(user,"accounts","GET",resource_owner_id="a")
check("user own route allowed",True)
try: wb_settings.authorize_route(user,"accounts","GET",resource_owner_id="b")
except wb_settings.AuthzError: check("user cross tenant denied",True)
else: check("user cross tenant denied",False)
wb_settings.authorize_route(admin,"accounts","GET",resource_owner_id="b")
check("admin app scope allowed",True)
wb_settings.authorize_route(local,"settings","POST")
check("local admin compatibility",True)
