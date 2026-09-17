#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workbuddy2api-hub 补丁：让 /v1/models 返回完整模型列表。

问题（hub v1.1.6）：
  1. CN realm 在容器里读不到桌面端缓存 ~/.workbuddy/cache/acc-product-config-v3.json，
     也没有 upstream 兜底，只能回落到内置 STATIC_CN_MODELS。
  2. merge_catalog() 把 CN_UI_ORDER 当"白名单"用（只输出在 order 里的模型），
     而 CN_UI_ORDER[0]="hy4-preview-f" 不在 CN 静态目录里、hy4-preview 又不在 order 里，
     两边一夹，hy4 系列直接被静默丢弃（50 -> 13）。

修复：
  1. 由外部挂载真实的产品配置缓存（见 hub_redeploy.sh 的 -v 挂载），本脚本不处理。
  2. 把 order 从"白名单"降级为"优先排序"：order 里的模型排在前面，
     其余模型按原顺序追加在后面，保证新模型永远不会被丢。
  3. CN_UI_ORDER 补上 hy4-preview，让它排在前面。

补充（dashboard.html）：
  面板上有两个按钮调用了页面里根本不存在的函数，点了没有任何反应（浏览器抛
  ReferenceError: xxx is not defined，表现为"点了没反应"）：
    - 「刷新额度/积分」onclick="fetchCredits(this)"，而页面只定义了 queryCredits；
    - 无账号时空态里的「登录新账号」onclick="startLogin()"，而页面只有 openLoginModal。
  两处都在本脚本里改成正确函数名，随重部署自动恢复。

幂等：重复执行不会产生重复补丁。
"""
import io
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/services/workbuddy2api-hub/wb_proxy.py")

MARK = "# PATCH(wb-hub-complete-models)"

OLD_MERGE = """    order = CN_UI_ORDER if r == "cn" else INTL_UI_ORDER
    out = []
    for mid in order:
        if mid in merged:
            out.append((mid, merged[mid]))
    return out
"""

NEW_MERGE = """    order = CN_UI_ORDER if r == "cn" else INTL_UI_ORDER
    out = []
    seen = set()
    for mid in order:
        if mid in merged:
            out.append((mid, merged[mid]))
            seen.add(mid)
    %s order 只是"优先排序"，不是白名单：
    # 未在 order 中出现的模型（比如后加入的 hy4-preview）按原顺序追加，避免被静默丢弃。
    for mid, meta in merged.items():
        if mid not in seen:
            out.append((mid, meta))
    return out
""" % MARK

OLD_ORDER = 'CN_UI_ORDER = [\n    "hy4-preview-f",\n    "hy3",\n'
NEW_ORDER = 'CN_UI_ORDER = [\n    "hy4-preview-f",\n    "hy4-preview",\n    "hy3",\n'

MARK2 = "# PATCH(wb-hub-public-models)"

OLD_AUTH = """        if path in ("/v1/models", "/models"):
            if not self._authorized():
                return
"""

NEW_AUTH = """        if path in ("/v1/models", "/models"):
            # %s 模型列表默认免鉴权（设 WB_PUBLIC_MODELS=0 恢复需要 key），
            # 这样 Codex++ 之类只认 base_url 的客户端也能自动补全下拉列表。
            if os.environ.get("WB_PUBLIC_MODELS", "1") != "1" and not self._authorized():
                return
""" % MARK2

MARK3 = "# PATCH(wb-hub-curated-models)"

OLD_TAIL = """    entries = merge_catalog(live, realm=r)
    with _lock:
        _models_cache[r] = {"at": time.time(), "data": entries}
    return entries
"""

NEW_TAIL = """    entries = merge_catalog(live, realm=r)
    entries = wb_patch_pick(entries, r)
    with _lock:
        _models_cache[r] = {"at": time.time(), "data": entries}
    return entries
"""

FUNC_ANCHOR = "def fetch_models(realm=None):"

PICK_FUNC = '''def wb_patch_pick(entries, r):
    """%s 精选模型列表：只暴露 WB_MODEL_PREFIXES 里的前缀。

    - WB_MODEL_PREFIXES  逗号分隔的前缀，如 "hy4,gpt"；留空 = 不过滤（返回全量）
    - WB_MODEL_EXCLUDE   逗号分隔的排除前缀，如 "hy4-preview-dev,hy4-preview-x"
    - CN 出口下会自动并入国际版静态目录，这样 gpt-* 这类只在国际版登记的
      模型也能出现在列表里。
    """
    pool = list(entries)
    if r == "cn":
        try:
            pool = pool + merge_catalog([], realm="intl")
        except Exception:
            pass

    # WB_MODEL_SET=official -> 只输出官方面板那两份清单（国际版 16 + 国内版 14 去重）
    if os.environ.get("WB_MODEL_SET", "").strip().lower() == "official":
        index = {}
        for mid, meta in pool:
            if mid and mid not in index:
                index[mid] = meta
        wanted = list(INTL_UI_ORDER) + [m for m in CN_UI_ORDER if m not in INTL_UI_ORDER]
        return [(m, index[m]) for m in wanted if m in index]

    prefixes = [p.strip().lower() for p in os.environ.get("WB_MODEL_PREFIXES", "").split(",") if p.strip()]
    if not prefixes:
        return entries
    excludes = [p.strip().lower() for p in os.environ.get("WB_MODEL_EXCLUDE", "").split(",") if p.strip()]
    out, seen = [], set()
    for mid, meta in pool:
        if not mid or mid in seen:
            continue
        low = mid.lower()
        if not any(low.startswith(p) for p in prefixes):
            continue
        if any(low.startswith(p) for p in excludes):
            continue
        seen.add(mid)
        out.append((mid, meta))
    order = CN_UI_ORDER if r == "cn" else INTL_UI_ORDER
    out.sort(key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order))
    return out


''' % MARK3


MARK4 = "# PATCH(wb-hub-auto-realm)"

# 上游把「未绑定出口的 key」又用 `or CURRENT_REALM` 兜回了全局出口，
# 于是面板上设成「跟随面板切换」的 key 实际被钉死在全局 realm，
# 拿它调另一个出口的模型就会 400 cross-realm。
AUTO_OLD_RE = re.compile(
    r"(?P<ind>[ ]+)req_realm = self\._request_realm\(\) or CURRENT_REALM\n"
    r"(?P=ind)blocked = self\._cross_realm_error\((?P<mv>.+?), req_realm\)\n"
    r"(?P=ind)if blocked:\n"
    r"(?P=ind)    return self\._error\(400, blocked, \"invalid_request_error\"\)\n"
)


def _auto_realm_sub(m):
    ind = m.group("ind")
    mv = m.group("mv")
    return (
        "%s# %s 未绑定出口的 key：把出口交给模型名自动判定\n" % (ind, MARK4)
        + "%sreq_realm = self._request_realm()\n" % ind
        + "%sif req_realm:\n" % ind
        + "%s    blocked = self._cross_realm_error(%s, req_realm)\n" % (ind, mv)
        + "%s    if blocked:\n" % ind
        + "%s        return self._error(400, blocked, \"invalid_request_error\")\n" % ind
    )


MARK5 = "PATCH(wb-hub-dashboard-buttons)"

# 上游 dashboard.html 里的按钮指向了不存在的函数，点了没反应。
# 左：页面里写的（错的）  中：真实存在的函数  右：说明
DASHBOARD_OLD = [
    ('onclick="fetchCredits(this)"', 'onclick="queryCredits(this)"',
     "刷新额度/积分按钮: fetchCredits -> queryCredits"),
    ('onclick="startLogin()"', 'onclick="openLoginModal()"',
     "空态[登录新账号]按钮: startLogin -> openLoginModal"),
]


MARK6 = "# PATCH(wb-hub-tasks-all)"

# 上游三个任务路由都写死 POOL.representative(realm="cn")，而 representative()
# 返回的是池子里**第一个**带 token 的号，于是面板上的「跑成长任务 / 猫猫旅行」
# 永远只作用在一个账号上，别的号碰不到。
# 这里改成：带 uid 只跑该号；不带 uid 依次跑该出口下所有可用号，返回汇总结果。
# 前端不用改 —— /tasks/run 读的是 r.logs（每条形如 "[昵称] ..."），
# /tasks/travel 读的是 r.msg（多号结果用换行拼起来）。

TASKS_FUNC = '''def wb_patch_task_targets(pool, uid=None, realm="cn"):
    """@@MARK@@ 成长任务 / 猫猫旅行的目标账号列表。

    - 传 uid   -> 只跑这一个号（保留原来的单号语义）
    - 不传 uid -> 依次跑该出口下所有带 token 的号
    """
    if pool is None:
        return []
    if uid:
        acc = pool.get(uid)
        return [acc] if acc else []
    return [a for a in getattr(pool, "accounts", [])
            if getattr(a, "realm", None) == realm and getattr(a, "access_token", None)]


'''.replace("@@MARK@@", MARK6)

OLD_TASKS_GET = """        if path == "/tasks":
            if not self._authorized():
                return
            acc = POOL.representative(realm="cn") if POOL else None
            if not acc:
                return self._json(200, {"tasks": [], "summary": {}, "msg": "未找到国内版可用账号"})
            from wb_tasks import fetch_growth_tasks, fetch_growth_summary
            tasks = fetch_growth_tasks(acc)
            summary = fetch_growth_summary(acc)
            return self._json(200, {"tasks": tasks, "summary": summary, "account": acc.public()})
"""

NEW_TASKS_GET = """        if path == "/tasks":
            if not self._authorized():
                return
            @@MARK@@ 支持 ?uid= 指定账号；不带 uid 时返回所有国内号（accounts 数组）
            from wb_tasks import fetch_growth_tasks, fetch_growth_summary
            targets = wb_patch_task_targets(POOL, (query.get("uid") or [None])[0])
            if not targets:
                return self._json(200, {"tasks": [], "summary": {}, "accounts": [],
                                        "msg": "未找到国内版可用账号"})
            collected = []
            for acc in targets:
                try:
                    collected.append({"account": acc.public(),
                                      "tasks": fetch_growth_tasks(acc),
                                      "summary": fetch_growth_summary(acc)})
                except Exception as exc:
                    collected.append({"account": acc.public(), "tasks": [],
                                      "summary": {}, "error": str(exc)})
            head = collected[0]
            # tasks/summary/account 仍给第一个号，保证老面板渲染不崩；
            # 多号明细放在 accounts 里。
            return self._json(200, {"tasks": head["tasks"], "summary": head["summary"],
                                    "account": head["account"], "accounts": collected})
""".replace("@@MARK@@", MARK6)

OLD_TASKS_RUN = """        if path == "/tasks/run":
            acc = POOL.representative(realm="cn") if POOL else None
            if not acc:
                return self._json(200, {"ok": False, "msg": "未找到国内版账号"})
            from wb_tasks import run_growth_tasks
            res = run_growth_tasks(acc, gap=1.0)
            return self._json(200, res)
"""

NEW_TASKS_RUN = """        if path == "/tasks/run":
            @@MARK@@ payload 带 uid 就只跑该号，否则依次跑所有国内号
            from wb_tasks import run_growth_tasks
            targets = wb_patch_task_targets(POOL, payload.get("uid"))
            if not targets:
                return self._json(200, {"ok": False, "msg": "未找到国内版可用账号"})
            results, logs, total = [], [], 0
            for acc in targets:
                tag = "[" + (acc.nickname or acc.uid[:8]) + "] "
                try:
                    res = run_growth_tasks(acc, gap=1.0) or {}
                except Exception as exc:
                    res = {"ok": False, "logs": ["执行异常: " + str(exc)]}
                sub = [tag + str(x) for x in (res.get("logs") or [])]
                if not sub:
                    sub = [tag + (res.get("msg") or ("完成" if res.get("ok") else "失败"))]
                logs.extend(sub)
                total += res.get("earned_credit") or 0
                results.append({"uid": acc.uid, "nickname": acc.nickname,
                                "ok": bool(res.get("ok")),
                                "earned_credit": res.get("earned_credit") or 0,
                                "credits": res.get("credits"), "logs": sub})
            return self._json(200, {
                "ok": all(r["ok"] for r in results),
                "logs": logs,
                "results": results,
                "earned_credit": total,
                "msg": "共 " + str(len(results)) + " 个账号，累计获得 " + str(total) + " 积分",
            })
""".replace("@@MARK@@", MARK6)

OLD_TASKS_TRAVEL = """        if path == "/tasks/travel":
            acc = POOL.representative(realm="cn") if POOL else None
            if not acc:
                return self._json(200, {"ok": False, "msg": "未找到国内版账号"})
            from wb_tasks import do_cat_travel
            res = do_cat_travel(acc)
            return self._json(200, res)
"""

NEW_TASKS_TRAVEL = """        if path == "/tasks/travel":
            @@MARK@@ 依次对所有国内号执行猫猫旅行（payload 带 uid 则只跑该号）
            from wb_tasks import do_cat_travel
            targets = wb_patch_task_targets(POOL, payload.get("uid"))
            if not targets:
                return self._json(200, {"ok": False, "msg": "未找到国内版可用账号"})
            results, msgs = [], []
            for acc in targets:
                tag = "[" + (acc.nickname or acc.uid[:8]) + "] "
                try:
                    res = do_cat_travel(acc) or {}
                except Exception as exc:
                    res = {"ok": False, "msg": "执行异常: " + str(exc)}
                msgs.append(tag + (res.get("msg") or ("完成" if res.get("ok") else "失败")))
                results.append({"uid": acc.uid, "nickname": acc.nickname,
                                "ok": bool(res.get("ok")), "action": res.get("action"),
                                "credit": res.get("credit"), "msg": res.get("msg")})
            return self._json(200, {
                "ok": all(r["ok"] for r in results),
                "results": results,
                "msg": "\\n".join(msgs),
            })
""".replace("@@MARK@@", MARK6)


MARK7 = "# PATCH(wb-hub-key-accounts)"

# 多租户的最小形态：一个 Key 只能用它绑定的那几个上游账号（A 用 1/2 号，B 用 3 号）。
# 租户身份不用新建 —— 请求进来时 `self.key_entry = identify_key(...)` 已经识别了调用方，
# 只需把它一路传到唯一的选号出口 open_upstream()，并在面板上给一个可勾选的账号列表。
#
# 设计约定：
#   - Key 不配 accounts（空数组/缺字段）= 不限制，行为和打补丁前完全一致（向后兼容）。
#   - 配了但那些账号后来被删/不存在了 -> 过滤后为空同样按「不限」处理，
#     宁可放宽也不让这个 Key 彻底不可用。
#   - 会话粘性必须带上租户前缀，否则两个租户撞了同一个 conversation_id 会共用账号绑定。

OLD_SETTINGS_ENTRY = '''    return {
        "id": str(entry.get("id") or secrets.token_hex(6)),
        "name": str(entry.get("name") or "").strip() or "未命名",
        "key": key,
        "realm": realm,
        "enabled": entry.get("enabled", True) is not False,
    }
'''

NEW_SETTINGS_ENTRY = '''    @@MARK@@ 这个函数的返回字典是硬编码的白名单，
    # 不在这里放行的话 accounts 会被静默丢掉（面板看着存进去了，重启就没了）。
    accounts = entry.get("accounts")
    if isinstance(accounts, (list, tuple)):
        accounts = [str(x).strip() for x in accounts if str(x).strip()]
    else:
        accounts = []
    return {
        "id": str(entry.get("id") or secrets.token_hex(6)),
        "name": str(entry.get("name") or "").strip() or "未命名",
        "key": key,
        "realm": realm,
        "enabled": entry.get("enabled", True) is not False,
        "accounts": accounts,
    }
'''.replace("@@MARK@@", MARK7)

TASKS_FUNC_MARK7 = '''def wb_patch_key_uids(key_entry):
    """@@MARK@@ 取出某个 Key 允许使用的账号 uid 集合。

    返回 None 表示「不限制」（没配 / 配的账号都不存在了），返回 set 表示只许用这些号。
    """
    entry = key_entry or {}
    raw = entry.get("accounts")
    if not isinstance(raw, (list, tuple)):
        return None
    wanted = set(str(x).strip() for x in raw if str(x).strip())
    if not wanted or POOL is None:
        return None
    known = set(a.uid for a in POOL.accounts)
    uids = wanted & known
    return uids or None


def wb_patch_tenant_session_key(session_key, key_entry):
    """@@MARK@@ 给会话粘性的 key 加上租户前缀。

    上游的 extract_session_key() 只看 X-Conversation-Id / payload 的 conversation_id，
    不含调用方身份；两个租户若撞了同一个 id 会共享同一个账号绑定，白名单就形同虚设。
    """
    if not session_key:
        return None
    entry = key_entry or {}
    owner = str(entry.get("id") or "").strip() or str(entry.get("key") or "")[:8] or "anon"
    return "%s::%s" % (owner, session_key)


'''.replace("@@MARK@@", MARK7)

OLD_OPEN_SIG = "def open_upstream(payload, session_key=None, target_realm=None):"
NEW_OPEN_SIG = "def open_upstream(payload, session_key=None, target_realm=None, allow=None):"

OLD_OPEN_LOOP = """        if account.realm != realm:
            if session_key and POOL: POOL.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
"""

NEW_OPEN_LOOP = """        if account.realm != realm:
            if session_key and POOL: POOL.affinity.unbind(session_key)
            continue
        @@MARK@@ 越界的号直接跳过并拉黑，交还给轮询找下一个
        if allow is not None and account.uid not in allow:
            if session_key and POOL: POOL.affinity.unbind(session_key)
            tried.add(account.uid)
            continue
        tried.add(account.uid)
""".replace("@@MARK@@", MARK7)

# 两处调用点文本完全一致（chat/completions 与 responses），逐处替换。
OLD_CALL_RESP = "upstream, account = open_upstream(chat_req, session_key=session_key, target_realm=req_realm)"
NEW_CALL_RESP = (
    "upstream, account = open_upstream(chat_req, session_key=session_key,\n"
    "                                        target_realm=req_realm,\n"
    "                                        allow=wb_patch_key_uids(self.key_entry))"
)

OLD_CALL_CHAT = "upstream, account = open_upstream(payload, session_key=session_key, target_realm=req_realm)"
NEW_CALL_CHAT = (
    "upstream, account = open_upstream(payload, session_key=session_key,\n"
    "                                       target_realm=req_realm,\n"
    "                                       allow=wb_patch_key_uids(self.key_entry))"
)
OLD_SESSION = "        session_key = extract_session_key(self.headers, payload)\n"
NEW_SESSION = (
    "        session_key = extract_session_key(self.headers, payload)\n"
    "        @@MARK@@ 会话粘性隔离到租户维度\n"
    "        session_key = wb_patch_tenant_session_key(session_key, self.key_entry)\n"
).replace("@@MARK@@", MARK7)

OLD_VIEW_KEY = '''        keys.append({
            "id": entry.get("id") or "",
            "name": entry.get("name") or "",
            "realm": entry.get("realm") or "",
            "enabled": entry.get("enabled", True) is not False,
            "masked": (raw[:4] + "*" * 6 + raw[-4:]) if len(raw) > 8 else "*" * len(raw),
            "source": entry.get("source") or "panel",
        })
'''
NEW_VIEW_KEY = '''        keys.append({
            "id": entry.get("id") or "",
            "name": entry.get("name") or "",
            "realm": entry.get("realm") or "",
            "enabled": entry.get("enabled", True) is not False,
            @@MARK@@ 面板要拿已勾选的账号来回显
            "accounts": entry.get("accounts") or [],
            "masked": (raw[:4] + "*" * 6 + raw[-4:]) if len(raw) > 8 else "*" * len(raw),
            "source": entry.get("source") or "panel",
        })
'''.replace("@@MARK@@", MARK7)

OLD_VIEW_RET = '''    return {
        "panel_password_is_default": wb_settings.panel_password_is_default(ACCOUNTS_DIR),
'''
NEW_VIEW_RET = '''    @@MARK@@ 给面板的「限定账号」勾选框提供候选（不过滤 realm，跨出口也要能选）
    _acct_opts = []
    try:
        for _a in (account_views() if POOL else []):
            _acct_opts.append({
                "uid": _a.get("uid") or "",
                "nickname": _a.get("nickname") or (_a.get("uid") or "")[:8],
                "realm": _a.get("realm") or "",
            })
    except Exception:
        _acct_opts = []
    return {
        "account_options": _acct_opts,
        "panel_password_is_default": wb_settings.panel_password_is_default(ACCOUNTS_DIR),
'''.replace("@@MARK@@", MARK7)

OLD_SAVE_ITEM = '''                cleaned.append({
                    "id": entry_id,
                    "name": str(item.get("name") or "").strip(),
                    "key": value,
                    "realm": realm,
                    "enabled": item.get("enabled", True) is not False,
                })
'''
NEW_SAVE_ITEM = '''                @@MARK@@ 面板勾选的账号白名单，空 = 不限
                accounts = item.get("accounts")
                if isinstance(accounts, (list, tuple)):
                    accounts = [str(x).strip() for x in accounts if str(x).strip()]
                else:
                    accounts = []
                cleaned.append({
                    "id": entry_id,
                    "name": str(item.get("name") or "").strip(),
                    "key": value,
                    "realm": realm,
                    "enabled": item.get("enabled", True) is not False,
                    "accounts": accounts,
                })
'''.replace("@@MARK@@", MARK7)

# ---------------- dashboard.html：给每个 Key 一行「限定账号」勾选框 ----------------
DASH_OLD_ROWS = """      realm: k.realm || '',
      enabled: k.enabled !== false,
    }));
    renderKeyRows();
"""
DASH_NEW_ROWS = """      realm: k.realm || '',
      enabled: k.enabled !== false,
      accounts: k.accounts || [],
    }));
    window.ACCOUNT_OPTIONS = data.account_options || [];
    renderKeyRows();
"""

DASH_ANCHOR = "function renderKeyRows(){"
DASH_HELPERS = """function keyAccountChips(index, row){
  const opts = (window.ACCOUNT_OPTIONS && window.ACCOUNT_OPTIONS.length)
    ? window.ACCOUNT_OPTIONS : (window.ACCOUNTS || []);
  const picked = new Set(row.accounts || []);
  if(!opts.length){
    return '<div style="width:100%;font-size:12px;color:var(--dim)">还没有可选账号，先到账号页登录</div>';
  }
  const chips = opts.map(o => {
    const uid = o.uid || '';
    const label = (o.nickname || uid.slice(0,8)) + (o.realm ? ' · ' + o.realm : '');
    return '<label style="display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--fg);'
      + 'background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:4px 10px;cursor:pointer">'
      + '<input type="checkbox"' + (picked.has(uid) ? ' checked' : '')
      + ` onchange="toggleKeyAccount(${index}, '${uid}', this.checked)">`
      + esc(label) + '</label>';
  }).join('');
  return '<div style="width:100%;display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
    + '<span style="font-size:12px;color:var(--dim)">限定账号</span>' + chips
    + '<span style="font-size:11px;color:var(--dim)">都不选 = 不限，可用全部账号</span></div>';
}

function toggleKeyAccount(index, uid, checked){
  const row = API_KEY_ROWS[index];
  if(!row) return;
  const picked = new Set(row.accounts || []);
  if(checked) picked.add(uid); else picked.delete(uid);
  row.accounts = Array.from(picked);
  renderKeyRows();
}

"""

DASH_OLD_MASKED = "      + maskedHint\n      + '</div>';"
DASH_NEW_MASKED = "      + keyAccountChips(i, row)\n      + maskedHint\n      + '</div>';"

DASH_OLD_SAVE = """    key: (row.key || '').trim(),
  }));"""
DASH_NEW_SAVE = """    key: (row.key || '').trim(),
    accounts: (row.accounts || []).slice(),
  }));"""


# ---------------- wb_proxy.py：冷却时长按「这个 Key 真用得上的号」收敛 ----------------
#
# 背景（2026-09-17 实测）：某个 Key 只绑了 1 个账号，那个号被上游 429 之后，
#   open_upstream 里 total = POOL.count_ready(realm) 取的是**全局** ready 数，
#   而 count_ready() 既不排除冷却中的号、也不看 Key 白名单 —— 池里有 3 个 cn 号时 total=3，
#   于是 single_account=False，note_error 走满 300 秒冷却。
#   这个 Key 白名单里就 1 个号，冷却期内选不到任何允许账号 => 5 分钟内所有请求 503。
# 修法：把 total 收敛到白名单内的可用数。只剩 1 个时 single_account=True，
#   note_error() 会走 3 秒短冷却（wb_accounts.py:396），抖动后几乎无感。
MARK8 = "PATCH(wb-hub-cooloff-scope)"
MARK10 = "# PATCH(wb-hub-account-alias)"

OLD_TOTAL_LINE = "    total = max(1, POOL.count_ready(realm)) if POOL else 1\n"
NEW_TOTAL_LINE = '''    total = max(1, POOL.count_ready(realm)) if POOL else 1
    # @@MARK@@ 冷却时长要按「这个 Key 真正用得上的号」算，不能拿全局 ready 数。
    # 只有 1 个可用号时让 note_error 走 3 秒短冷却，避免一次 429 就把该 Key 冻死 5 分钟。
    if POOL and allow:
        _allowed = sum(1 for _a in POOL.accounts
                       if _a.uid in allow and _a.realm == realm
                       and _a.enabled and _a.access_token)
        if _allowed:
            total = _allowed
'''.replace("@@MARK@@", MARK8)


# ---------------- 账号别名（MARK9）----------------
#
# 账号的默认显示名是上游昵称（手机号 / 微信名之类），多个号放在一起很难认。
# 别名存在 settings.json 的 account_aliases 里（uid -> 别名），不动账号文件本身
# ——账号 JSON 会被登录/刷新重写，写进去迟早被冲掉。
ALIAS_FUNCS = '''

def account_aliases(accounts_dir):
    """@@MARK@@ 账号别名表：uid -> 别名。空值会被丢掉，等于该号用回上游昵称。"""
    data = load(accounts_dir)
    raw = data.get("account_aliases")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        uid = str(key or "").strip()
        name = str(value or "").strip()
        if uid and name:
            out[uid] = name
    return out


def set_account_aliases(accounts_dir, mapping):
    """整体覆盖别名表（面板每次提交全量）。"""
    data = load(accounts_dir)
    raw = mapping if isinstance(mapping, dict) else {}
    out = {}
    for key, value in raw.items():
        uid = str(key or "").strip()
        name = str(value or "").strip()
        if uid and name:
            out[uid] = name
    data["account_aliases"] = out
    save(accounts_dir, data)
    return out
'''.replace("@@MARK@@", MARK10)

# wb_proxy.py 侧的读取 helper：按 settings.json 的 mtime 缓存，
# 因为面板几秒就轮询一次 /accounts，没必要每次都读盘。
ALIAS_PROXY_FUNC = '''_WB_PATCH_ALIAS_CACHE = {"stamp": 0, "data": {}}


def wb_patch_account_aliases():
    """@@MARK@@ 账号别名表（uid -> 别名），按 settings.json 的 mtime 缓存。"""
    try:
        stamp = os.path.getmtime(wb_settings.settings_path(ACCOUNTS_DIR))
    except Exception:
        stamp = 0
    if _WB_PATCH_ALIAS_CACHE.get("stamp") != stamp:
        try:
            data = wb_settings.account_aliases(ACCOUNTS_DIR)
        except Exception:
            data = {}
        _WB_PATCH_ALIAS_CACHE["stamp"] = stamp
        _WB_PATCH_ALIAS_CACHE["data"] = data
    return _WB_PATCH_ALIAS_CACHE.get("data") or {}


'''.replace("@@MARK@@", MARK10)

# account_views()：/accounts 与「限定账号」候选都走这里
OLD_ACCOUNT_VIEWS = '''def account_views(realm=None):
    """List view of every account, including a live readiness flag."""
    if not POOL:
        return []
    return POOL.list_public(realm=realm)
'''

NEW_ACCOUNT_VIEWS = '''def account_views(realm=None):
    """List view of every account, including a live readiness flag."""
    if not POOL:
        return []
    views = POOL.list_public(realm=realm)
    @@MARK@@ 带上自定义别名；面板各处优先显示 alias，没有才回落到上游昵称
    aliases = wb_patch_account_aliases()
    for view in views:
        view["alias"] = aliases.get(view.get("uid") or "") or ""
    return views
'''.replace("@@MARK@@", MARK10)

# 看板「按账号」聚合也要带别名，否则同一个号在两处两个名字
OLD_ACCTS_SORT = '''    accts_list = sorted(acct_map.values(), key=lambda a: (-a["today"]["total_tokens"], -a["all_time"]["total_tokens"]))
'''

NEW_ACCTS_SORT = '''    @@MARK@@ 看板按账号聚合同样带别名
    _alias_map = wb_patch_account_aliases()
    for _acct in acct_map.values():
        _acct["alias"] = _alias_map.get(_acct.get("uid") or "") or ""
    accts_list = sorted(acct_map.values(), key=lambda a: (-a["today"]["total_tokens"], -a["all_time"]["total_tokens"]))
'''.replace("@@MARK@@", MARK10)

# 设置回显：把整张别名表给前端，前端任何位置都能按 uid 反查
# 注意：这段必须在 MARK7 的 OLD_VIEW_RET 替换之后执行（彼时 return 里已有 account_options）
OLD_VIEW_ALIAS = '''        "account_options": _acct_opts,
        "panel_password_is_default": wb_settings.panel_password_is_default(ACCOUNTS_DIR),
'''

NEW_VIEW_ALIAS = '''        "account_options": _acct_opts,
        @@MARK@@ 整张别名表给前端，任务页/看板都能按 uid 反查显示名
        "account_aliases": wb_patch_account_aliases(),
        "panel_password_is_default": wb_settings.panel_password_is_default(ACCOUNTS_DIR),
'''.replace("@@MARK@@", MARK10)

# 保存：/settings/save 接收 account_aliases
OLD_SAVE_ALIAS = '''            reply["api_keys_saved"] = len(cleaned)

        if "auth_disabled" in payload:
'''

NEW_SAVE_ALIAS = '''        if "account_aliases" in payload:
            @@MARK@@ 账号别名：整体覆盖（面板传全量映射，留空即恢复默认名）
            raw_alias = payload.get("account_aliases")
            if not isinstance(raw_alias, dict):
                return self._error(400, "account_aliases must be an object",
                                   "invalid_request_error")
            reply["account_aliases"] = wb_settings.set_account_aliases(ACCOUNTS_DIR, raw_alias)

        if "auth_disabled" in payload:
'''.replace("@@MARK@@", MARK10)


def patch_settings(path):
    """给 wb_settings.py 打 accounts 白名单补丁（幂等）。"""
    if not os.path.exists(path):
        print("  [warn] 没找到 wb_settings.py: %s" % path, file=sys.stderr)
        return False
    with io.open(path, encoding="utf-8") as fh:
        src = fh.read()
    original = src

    if NEW_SETTINGS_ENTRY in src:
        print("  [skip] wb_settings.py 已支持 key -> accounts")
    elif OLD_SETTINGS_ENTRY in src:
        src = src.replace(OLD_SETTINGS_ENTRY, NEW_SETTINGS_ENTRY, 1)
        print("  [ok] wb_settings.py: key 条目保留 accounts 白名单")
    else:
        print("  [warn] wb_settings.py 没找到目标片段 —— 可能上游改了代码，请人工确认",
              file=sys.stderr)

    if "def account_aliases(" in src:
        print("  [skip] wb_settings.py 已支持账号别名")
    else:
        src = src.rstrip() + "\n" + ALIAS_FUNCS
        print("  [ok] wb_settings.py: 账号别名读写（account_aliases / set_account_aliases）")

    if src == original:
        return False

    bak = path + ".orig"
    if not os.path.exists(bak):
        try:
            with io.open(bak, "w", encoding="utf-8") as fh:
                fh.write(io.open(path, encoding="utf-8").read())
        except Exception:
            pass
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(src)
    print("  [ok] wb_settings.py: key 条目保留 accounts 白名单")
    return True


KEY_UI_STEPS = (
    (DASH_ANCHOR, DASH_HELPERS + DASH_ANCHOR, "注入 keyAccountChips / toggleKeyAccount"),
    (DASH_OLD_ROWS, DASH_NEW_ROWS, "Key 行读入 accounts + 账号候选清单"),
    (DASH_OLD_MASKED, DASH_NEW_MASKED, "Key 行渲染「限定账号」勾选框"),
    (DASH_OLD_SAVE, DASH_NEW_SAVE, "保存时带上 accounts"),
)

# ---------------- dashboard.html：勾选框 -> 带搜索的下拉多选（MARK9）----------------
#
# chips 在账号少的时候够用，账号一多就铺满整行、找不到目标。改成下拉：
# 触发器显示「不限 / 已选 N 个」，展开后是 搜索框 + 复选框列表 + 全选/清空。
# 注意两个实现细节：
#   - 勾选/搜索都只改局部 DOM（不调 renderKeyRows），否则输入框会失焦、面板会被关掉；
#   - toggleKeyAccount 同名覆盖 MARK7 的版本（本段注入在其后），后者会整体重绘。
DROPDOWN_HELPERS = """/* Key 账号白名单：下拉多选 + 搜索 */
var KEY_ACCT_UI = { open: -1, filter: '' };

function keyAccountOptions(){
  return (window.ACCOUNT_OPTIONS && window.ACCOUNT_OPTIONS.length)
    ? window.ACCOUNT_OPTIONS : (window.ACCOUNTS || []);
}

function keyAccountPicked(index){
  var row = API_KEY_ROWS[index] || {};
  return new Set(row.accounts || []);
}

function keyAccountSummary(index){
  var picked = keyAccountPicked(index);
  if(!picked.size) return '不限（全部账号）';
  var names = keyAccountOptions().filter(function(o){ return picked.has(o.uid || ''); })
    .map(function(o){ return o.nickname || String(o.uid || '').slice(0, 8); });
  if(names.length <= 2) return names.join('、');
  return names[0] + ' 等 ' + names.length + ' 个';
}

function keyAccountListHtml(index){
  var q = String(KEY_ACCT_UI.filter || '').toLowerCase();
  var picked = keyAccountPicked(index);
  var opts = keyAccountOptions().filter(function(o){
    if(!q) return true;
    var hay = ((o.nickname || '') + ' ' + (o.uid || '') + ' ' + (o.realm || '')).toLowerCase();
    return hay.indexOf(q) >= 0;
  });
  if(!opts.length){
    return '<div style="padding:8px 10px;font-size:12px;color:var(--dim)">没有匹配的账号</div>';
  }
  return opts.map(function(o){
    var uid = String(o.uid || '');
    var label = (o.nickname || uid.slice(0, 8)) + (o.realm ? ' · ' + o.realm : '');
    return '<label style="display:flex;align-items:center;gap:8px;padding:6px 10px;font-size:12px;cursor:pointer">'
      + '<input type="checkbox"' + (picked.has(uid) ? ' checked' : '')
      + ` onchange="toggleKeyAccount(${index}, '${uid}', this.checked)">`
      + '<span>' + esc(label) + '</span></label>';
  }).join('');
}

function keyAccountDropdown(index, row){
  var opts = keyAccountOptions();
  if(!opts.length){
    return '<div style="width:100%;font-size:12px;color:var(--dim)">还没有可选账号，先到账号页登录</div>';
  }
  var open = KEY_ACCT_UI.open === index;
  return '<div class="kac-wrap" style="position:relative;width:100%">'
    + '<button type="button" onclick="event.stopPropagation();toggleKeyAccountPanel(' + index + ')"'
    + ' style="display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--fg);'
    + ' background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 10px;cursor:pointer">'
    + '<span style="color:var(--dim)">限定账号</span>'
    + '<span id="kac-sum-' + index + '">' + esc(keyAccountSummary(index)) + '</span>'
    + '<span>▾</span></button>'
    + '<div id="kac-panel-' + index + '" onclick="event.stopPropagation()"'
    + ' style="display:' + (open ? 'block' : 'none') + ';position:absolute;z-index:80;left:0;top:calc(100% + 4px);'
    + ' min-width:280px;background:var(--panel);border:1px solid var(--line);border-radius:10px;'
    + ' box-shadow:0 8px 24px rgba(0,0,0,.18);padding:6px">'
    + '<input id="kac-q-' + index + '" type="text" placeholder="搜索账号名 / uid"'
    + ' value="' + esc(KEY_ACCT_UI.filter || '') + '"'
    + ' oninput="filterKeyAccounts(' + index + ', this.value)"'
    + ' style="width:100%;box-sizing:border-box;font-size:12px;padding:5px 8px;margin-bottom:4px;'
    + ' border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)">'
    + '<div id="kac-list-' + index + '" style="max-height:220px;overflow:auto">'
    + keyAccountListHtml(index) + '</div>'
    + '<div style="display:flex;gap:12px;align-items:center;padding:6px 10px 2px;font-size:11px;'
    + ' border-top:1px solid var(--line);margin-top:4px;color:var(--dim)">'
    + '<a href="javascript:void(0)" onclick="pickAllKeyAccounts(' + index + ', true)" style="color:var(--dim)">全选</a>'
    + '<a href="javascript:void(0)" onclick="pickAllKeyAccounts(' + index + ', false)" style="color:var(--dim)">清空</a>'
    + '<span style="margin-left:auto">清空 = 不限</span></div>'
    + '</div></div>';
}

function toggleKeyAccountPanel(index){
  KEY_ACCT_UI.open = (KEY_ACCT_UI.open === index) ? -1 : index;
  KEY_ACCT_UI.filter = '';
  renderKeyRows();
  if(KEY_ACCT_UI.open === index){
    var q = document.getElementById('kac-q-' + index);
    if(q) q.focus();
  }
}

function filterKeyAccounts(index, val){
  KEY_ACCT_UI.filter = val || '';
  var box = document.getElementById('kac-list-' + index);
  if(box) box.innerHTML = keyAccountListHtml(index);
}

function toggleKeyAccount(index, uid, checked){
  var row = API_KEY_ROWS[index];
  if(!row) return;
  var picked = new Set(row.accounts || []);
  if(checked) picked.add(uid); else picked.delete(uid);
  row.accounts = Array.from(picked);
  var sum = document.getElementById('kac-sum-' + index);
  if(sum) sum.textContent = keyAccountSummary(index);
}

function pickAllKeyAccounts(index, all){
  var row = API_KEY_ROWS[index];
  if(!row) return;
  row.accounts = all
    ? keyAccountOptions().map(function(o){ return String(o.uid || ''); }).filter(Boolean)
    : [];
  var box = document.getElementById('kac-list-' + index);
  if(box) box.innerHTML = keyAccountListHtml(index);
  var sum = document.getElementById('kac-sum-' + index);
  if(sum) sum.textContent = keyAccountSummary(index);
}

document.addEventListener('click', function(){
  if(KEY_ACCT_UI.open !== -1){
    KEY_ACCT_UI.open = -1;
    KEY_ACCT_UI.filter = '';
    renderKeyRows();
  }
});

"""

DROPDOWN_UI_STEPS = (
    (DASH_ANCHOR, DROPDOWN_HELPERS + DASH_ANCHOR, "注入账号下拉多选（带搜索）"),
    ("      + keyAccountChips(i, row)", "      + keyAccountDropdown(i, row)",
     "Key 行的账号选择改用下拉框"),
)


# ---------------- 账号别名 + 任务页选号（MARK10 前端）----------------
#
# 显示名统一收敛到 accName()：alias > 全局别名表（按 uid 反查）> 上游昵称 > uid 前 8 位。
# 必须支持「按 uid 反查」：Key 下拉和任务页里的对象是后端拼的，没有 alias 字段，
# 只有 /accounts 与看板带 alias，靠 uid 查表才能让所有位置显示成同一个名字。
ALIAS_ANCHOR = "async function loadGrowthTasks(){\n"

ALIAS_UI_HELPERS = """/* 账号别名：面板上账号默认显示上游昵称，不好辨认，允许自定义 */
window.ACCOUNT_ALIASES = window.ACCOUNT_ALIASES || {};

function accAlias(uid){
  if(!uid) return '';
  return (window.ACCOUNT_ALIASES || {})[uid] || '';
}

function accName(a){
  if(!a) return '';
  if(a.alias) return a.alias;
  const byUid = accAlias(a.uid);
  if(byUid) return byUid;
  return a.nickname || (a.uid ? String(a.uid).slice(0, 8) : '');
}

async function editAccountAlias(uid, current){
  const input = prompt('给这个账号起个别名（留空则恢复默认显示）：', current || '');
  if(input === null) return;
  const value = String(input).trim();
  const map = Object.assign({}, window.ACCOUNT_ALIASES || {});
  if(value) map[uid] = value; else delete map[uid];
  try{
    await postJSON('/settings/save', {account_aliases: map});
    window.ACCOUNT_ALIASES = map;
    await loadAccounts();
    if(typeof loadSettings === 'function') loadSettings(false);
    toast('别名已保存', 'ok');
  }catch(e){
    toast('保存失败: ' + e.message, 'bad');
  }
}

/* 任务页：可以只对某个账号做任务，不选则依次跑所有国内号 */
window.TASK_UID = '';

function taskAccountOptions(){
  return (window.ACCOUNTS || []).filter(function(a){ return a.realm === 'cn'; });
}

function renderTaskAccountSel(){
  const sel = document.getElementById('taskAccountSel');
  if(!sel) return;
  const list = taskAccountOptions();
  if(window.TASK_UID && !list.some(function(a){ return a.uid === window.TASK_UID; })){
    window.TASK_UID = '';
  }
  sel.innerHTML = '<option value="">全部账号（依次执行）</option>' + list.map(function(a){
    return '<option value="' + esc(a.uid) + '"'
      + (a.uid === window.TASK_UID ? ' selected' : '') + '>' + esc(accName(a)) + '</option>';
  }).join('');
}

function onTaskAccountChange(value){
  window.TASK_UID = value || '';
  loadGrowthTasks();
}

function taskUid(){ return window.TASK_UID || ''; }

"""

ALIAS_UI_STEPS = (
    (ALIAS_ANCHOR, ALIAS_UI_HELPERS + ALIAS_ANCHOR,
     "注入 accName / 别名编辑 / 任务选号函数"),
    ("    window.ACCOUNT_OPTIONS = data.account_options || [];",
     "    window.ACCOUNT_OPTIONS = data.account_options || [];\n"
     "    window.ACCOUNT_ALIASES = data.account_aliases || {};",
     "设置里读入别名表"),
    ('        <button class="primary" id="btnRunTasks" onclick="runGrowthTasks(this)">一键做任务领积分</button>',
     '        <select id="taskAccountSel" onchange="onTaskAccountChange(this.value)"'
     ' title="选择要执行任务的账号"'
     ' style="padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--text)"></select>\n'
     '        <button class="primary" id="btnRunTasks" onclick="runGrowthTasks(this)">一键做任务领积分</button>',
     "任务页加账号下拉"),
    ("  sec.style.display = 'block';",
     "  sec.style.display = 'block';\n  renderTaskAccountSel();",
     "渲染任务页账号下拉"),
    ("    const r = await getJSON('/tasks');",
     "    const r = await getJSON('/tasks' + (taskUid() ? ('?uid=' + encodeURIComponent(taskUid())) : ''));",
     "任务查询带 uid"),
    ('const r = await postJSON("/tasks/run", {});',
     'const r = await postJSON("/tasks/run", {uid: taskUid()});',
     "跑成长任务带 uid"),
    ('const r = await postJSON("/tasks/travel", {});',
     'const r = await postJSON("/tasks/travel", {uid: taskUid()});',
     "猫猫旅行带 uid"),
    ("+ state + ' ' + realmBadge + '</div>'",
     "+ state + ' ' + realmBadge"
     " + ' <a href=\"javascript:void(0)\" style=\"opacity:.6;text-decoration:none\" title=\"设置别名\""
     " onclick=\"editAccountAlias(&quot;' + a.uid + '&quot;,&quot;' + esc(a.alias || '') + '&quot;)\">&#9998;</a>'"
     " + '</div>'"
     " + (a.alias ? '<div class=\"mono\" style=\"color:var(--dim);font-size:10px\">"
     "原昵称: ' + esc(a.nickname) + '</div>' : '')",
     "账号行加别名编辑入口（有别名时显示原昵称）"),
)

# 显示名统一改成 accName()。长片段放前面，避免被短片段先替换掉。
ALIAS_NAME_SUBS = (
    ("esc(a.nickname || a.uid)", "esc(accName(a))"),
    ("esc(a.nickname)", "esc(accName(a))"),
    ("+ (r.account && r.account.nickname) +", "+ accName(r.account) +"),
    ("(x.nickname||x.uid.slice(0,6))", "accName(x)"),
    ("esc(d.nickname || (d.uid||'').slice(0,8))", "esc(accName(d))"),
    ("(a.nickname || (a.uid||'').slice(0,8))", "accName(a)"),
    ("esc(info.nickname || uid.slice(0, 8))", "esc(accName(info))"),
    ("esc(info.nickname || uid.slice(0, 6))", "esc(accName(info))"),
    ("(o.nickname || uid.slice(0,8)) + (o.realm ? ' · ' + o.realm : '')",
     "accName(o) + (o.realm ? ' · ' + o.realm : '')"),
    ("return o.nickname || String(o.uid || '').slice(0, 8);", "return accName(o);"),
    ("var hay = ((o.nickname || '') + ' ' + (o.uid || '') + ' ' + (o.realm || '')).toLowerCase();",
     "var hay = ((o.nickname || '') + ' ' + (o.alias || '') + ' ' + accAlias(o.uid)"
     " + ' ' + (o.uid || '') + ' ' + (o.realm || '')).toLowerCase();"),
)


# ---------------- 用量流水增加 API Key 维度（MARK11）----------------
#
# 网关本来就 identify_key() 认出了调用方，但结果只用来取 realm，没写进流水，
# 所以「谁用了多少」是算不出来的。这里补两件事：
#   1) 把 Key 身份存进 thread-local（ThreadingHTTPServer 是多线程，不能用全局），
#      record_usage / record_error 直接读，省得改六处调用点签名；
#   2) usage_by_key() 按 Key 聚合，看板新增一张表。
# 注意：埋点之前的流水没有 key 字段，会单独聚成「(埋点前)」，无法回填。
MARK11 = "# PATCH(wb-hub-usage-key)"

USAGE_KEY_FUNC = '''_WB_PATCH_KEY_TLS = threading.local()


def wb_patch_set_key(entry):
    """@@MARK@@ 记住当前请求用的是哪个 API Key（供 record_usage 读取）。"""
    entry = entry or {}
    _WB_PATCH_KEY_TLS.key_id = str(entry.get("id") or "")
    _WB_PATCH_KEY_TLS.key_name = str(entry.get("name") or "")


def wb_patch_key_fields():
    """当前请求的 Key 维度字段；取不到就是空串（见 usage_by_key 的「(埋点前)」）。"""
    return {
        "key_id": getattr(_WB_PATCH_KEY_TLS, "key_id", "") or "",
        "key_name": getattr(_WB_PATCH_KEY_TLS, "key_name", "") or "",
    }


def usage_by_key():
    """@@MARK@@ 按 API Key 聚合用量流水 —— 多租户场景下看「谁用了多少」。"""
    buckets = {}
    try:
        with open(USAGE_LOG, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                kid = str(row.get("key_id") or "")
                kname = str(row.get("key_name") or "")
                token = kid or kname or "(埋点前)"
                bucket = buckets.setdefault(token, {
                    "key_id": kid, "key_name": kname,
                    "label": kname or kid or "(埋点前)",
                    "requests": 0, "errors": 0, "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0, "credit": 0.0,
                    "models": {}, "accounts": {},
                })
                if row.get("error"):
                    bucket["errors"] += 1
                    continue
                bucket["requests"] += 1
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    bucket[field] += row.get(field) or 0
                try:
                    bucket["credit"] += float(row.get("credit") or 0)
                except (TypeError, ValueError):
                    pass
                model = row.get("model") or "?"
                bucket["models"][model] = bucket["models"].get(model, 0) + 1
                acct = row.get("account") or "(unattributed)"
                bucket["accounts"][acct] = bucket["accounts"].get(acct, 0) + 1
    except Exception as exc:
        log("usage_by_key failed: %s" % exc)
    return sorted(buckets.values(), key=lambda b: (-b["total_tokens"], -b["requests"]))


'''.replace("@@MARK@@", MARK11)

# 认出 Key 之后立刻记下来
OLD_KEY_ENTRY_SET = '''        self.key_entry = identify_key(self._supplied_key())
'''

NEW_KEY_ENTRY_SET = '''        self.key_entry = identify_key(self._supplied_key())
        @@MARK@@ 记下调用方身份，供 record_usage / record_error 写入流水
        wb_patch_set_key(self.key_entry)
'''.replace("@@MARK@@", MARK11)

# 成功请求与失败请求都要带 Key 维度，否则失败率会算错
OLD_RECORD_USAGE = '''    if account:
        row["account"] = account
    acc = POOL.get(account) if (account and POOL) else None
'''

NEW_RECORD_USAGE = '''    if account:
        row["account"] = account
    @@MARK@@ 记下是哪个 Key 发起的
    row.update(wb_patch_key_fields())
    acc = POOL.get(account) if (account and POOL) else None
'''.replace("@@MARK@@", MARK11)

OLD_RECORD_ERROR = '''        "message": str(message)[:200],
        "elapsed_ms": elapsed_ms,
    }
'''

NEW_RECORD_ERROR = '''        "message": str(message)[:200],
        "elapsed_ms": elapsed_ms,
    }
    row.update(wb_patch_key_fields())
'''

OLD_USAGE_ROUTE = '''        if path == "/usage/recent":
'''

NEW_USAGE_ROUTE = '''        if path == "/usage/by-key":
            if not self._authorized():
                return
            return self._json(200, {"keys": usage_by_key()})
        if path == "/usage/recent":
'''

# 前端：看板追加「按 API Key」表格。容器是动态创建的，
# 这样不用去猜 pageAnalytics 里该插在哪一行 HTML 之后。
KEY_USAGE_UI = """/* 按 API Key 的用量（多租户出账） */
function keyUsageContainer(){
  var box = document.getElementById('keyUsageSection');
  if(box) return box;
  var host = document.getElementById('pageAnalytics');
  if(!host) return null;
  box = document.createElement('section');
  box.id = 'keyUsageSection';
  box.innerHTML = '<h2 style="margin:0 0 10px">按 API Key 用量</h2>'
    + '<div id="keyUsageBody" class="hint">加载中</div>';
  host.appendChild(box);
  return box;
}

async function loadKeyUsage(){
  var box = keyUsageContainer();
  if(!box) return;
  var body = document.getElementById('keyUsageBody');
  if(!body) return;
  try{
    var r = await getJSON('/usage/by-key');
    var rows = r.keys || [];
    if(!rows.length){
      body.innerHTML = '<p class="hint">暂无 Key 维度记录。埋点之前的流水无法回填，新请求会开始统计。</p>';
      return;
    }
    body.innerHTML = '<table class="tbl"><thead><tr>'
      + '<th>API Key</th><th>请求</th><th>失败</th><th>tokens</th><th>积分</th><th>命中账号</th>'
      + '</tr></thead><tbody>'
      + rows.map(function(k){
          var models = Object.keys(k.models || {}).slice(0, 3).join('、');
          var accts = Object.keys(k.accounts || {}).map(function(u){
            return (accName({uid: u}) || String(u).slice(0, 8)) + ' (' + k.accounts[u] + ')';
          }).join('、') || '-';
          return '<tr>'
            + '<td><b>' + esc(k.label || '(未命名)') + '</b>'
            + (k.key_id ? ' <span class="mono" style="color:var(--dim);font-size:11px">' + esc(k.key_id) + '</span>' : '')
            + (models ? '<div class="mono" style="font-size:11px;color:var(--dim)">' + esc(models) + '</div>' : '')
            + '</td>'
            + '<td>' + fmt(k.requests) + '</td>'
            + '<td>' + (k.errors ? '<span style="color:var(--warn)">' + k.errors + '</span>' : '0') + '</td>'
            + '<td>' + fmt(k.total_tokens) + '</td>'
            + '<td><b style="color:var(--accent2)">' + (k.credit || 0).toFixed(2) + '</b></td>'
            + '<td style="font-size:12px">' + esc(accts) + '</td>'
            + '</tr>';
        }).join('')
      + '</tbody></table>';
  }catch(e){
    body.innerHTML = '<p class="hint" style="color:var(--warn)">读取失败: ' + esc(e.message) + '</p>';
  }
}

setTimeout(loadKeyUsage, 1500);
setInterval(loadKeyUsage, 30000);

"""


def patch_dashboard(path):
    """给 dashboard.html 打前端补丁（幂等）。返回是否发生了改动。"""
    if not os.path.exists(path):
        print("  [warn] 没找到 dashboard.html: %s" % path, file=sys.stderr)
        return False

    with io.open(path, encoding="utf-8") as fh:
        html = fh.read()
    original = html
    notes = []

    # --- 第一组：失效按钮函数名（MARK5）---
    if MARK5 in html:
        print("  [skip] dashboard.html 按钮补丁已在")
    else:
        hits = [old for old, _new, _d in DASHBOARD_OLD if old in html]
        if not hits:
            print("  [warn] dashboard.html 里没找到失效按钮片段，可能上游已自行修复/改名 —— 请人工确认",
                  file=sys.stderr)
        else:
            for old, new, _d in DASHBOARD_OLD:
                html = html.replace(old, new)
            # 打上标记，避免重复执行；同时便于后续 --pull 后识别
            if MARK5 not in html:
                html = html.replace("<!doctype html>", "<!doctype html>\n<!-- %s -->" % MARK5, 1)
            for old, _new, desc in DASHBOARD_OLD:
                if old in hits:
                    notes.append(desc)

    # --- 第二组：Key -> 账号白名单 UI（MARK7）---
    # 关键点：不能因为 MARK5 已存在就提前 return，否则这一组永远打不上。
    if "keyAccountChips" in html:
        print("  [skip] dashboard.html Key 账号勾选框已在")
    else:
        for old, new, desc in KEY_UI_STEPS:
            if old not in html:
                print("  [warn] dashboard.html 缺少片段: " + desc + " —— 可能上游改了页面，请人工确认",
                      file=sys.stderr)
                continue
            html = html.replace(old, new, 1)
            notes.append(desc)

    # --- 第三组：账号选择从勾选框改成下拉（MARK9）---
    # 必须在第二组之后：本段依赖 MARK7 已写入的 keyAccountChips 调用点来替换。
    if "keyAccountDropdown" in html:
        print("  [skip] dashboard.html 账号下拉框已在")
    else:
        for old, new, desc in DROPDOWN_UI_STEPS:
            if old not in html:
                print("  [warn] dashboard.html 缺少片段: " + desc + " —— 可能上游改了页面，请人工确认",
                      file=sys.stderr)
                continue
            html = html.replace(old, new, 1)
            notes.append(desc)

    # --- 第四组：账号别名 + 任务页选号（MARK10）---
    if "function accName(" in html:
        print("  [skip] dashboard.html 账号别名已在")
    else:
        for old, new, desc in ALIAS_UI_STEPS:
            if old not in html:
                print("  [warn] dashboard.html 缺少片段: " + desc + " —— 可能上游改了页面，请人工确认",
                      file=sys.stderr)
                continue
            html = html.replace(old, new, 1)
            notes.append(desc)
        for old, new in ALIAS_NAME_SUBS:
            if old in html:
                html = html.replace(old, new)
        notes.append("账号显示名统一走 accName()")

    # --- 第五组：看板加「按 API Key 用量」表（MARK11）---
    if "function loadKeyUsage(" in html:
        print("  [skip] dashboard.html Key 用量表已在")
    elif ALIAS_ANCHOR in html:
        html = html.replace(ALIAS_ANCHOR, KEY_USAGE_UI + ALIAS_ANCHOR, 1)
        notes.append("看板追加「按 API Key 用量」表")
    else:
        print("  [warn] dashboard.html 找不到 %r 锚点，Key 用量表无法注入" % ALIAS_ANCHOR,
              file=sys.stderr)

    if html == original:
        return False

    # 备份一次未打补丁的原文件（与 wb_proxy.py.orig 同样的用途：--pull 前还原）
    bak = path + ".orig"
    if not os.path.exists(bak):
        try:
            with io.open(bak, "w", encoding="utf-8") as fh:
                fh.write(io.open(path, encoding="utf-8").read())
        except Exception:
            pass

    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(html)

    for desc in notes:
        print("  [ok] " + desc)
    return True


def main():
    with io.open(SRC, encoding="utf-8") as fh:
        src = fh.read()

    changed = []

    if MARK in src:
        print("  [skip] merge_catalog 已打过补丁")
    elif OLD_MERGE in src:
        src = src.replace(OLD_MERGE, NEW_MERGE, 1)
        changed.append("merge_catalog: order 降级为优先排序")
    else:
        print("  [warn] 没找到 merge_catalog 的目标片段，可能上游改了代码 —— 请人工确认", file=sys.stderr)

    if NEW_ORDER in src:
        print("  [skip] CN_UI_ORDER 已包含 hy4-preview")
    elif OLD_ORDER in src:
        src = src.replace(OLD_ORDER, NEW_ORDER, 1)
        changed.append("CN_UI_ORDER: 补入 hy4-preview")
    else:
        print("  [warn] 没找到 CN_UI_ORDER 的目标片段，可能上游改了代码 —— 请人工确认", file=sys.stderr)

    if MARK2 in src:
        print("  [skip] /v1/models 已支持免鉴权")
    elif OLD_AUTH in src:
        src = src.replace(OLD_AUTH, NEW_AUTH, 1)
        changed.append("/v1/models: 免鉴权（WB_PUBLIC_MODELS=0 可关闭）")
    else:
        print("  [warn] 没找到 /v1/models 鉴权片段，可能上游改了代码 —— 请人工确认", file=sys.stderr)

    # 精选函数采用"整块替换"，这样以后改函数内容也能靠重跑脚本升级
    if OLD_TAIL in src and FUNC_ANCHOR in src:
        if OLD_TAIL not in src:
            pass
        src = src.replace(OLD_TAIL, NEW_TAIL, 1)
    new_src = re.sub(r"\ndef wb_patch_pick\(.*?\n\n(?=def fetch_models\()", "\n", src, flags=re.S)
    if PICK_FUNC.strip() not in new_src:
        new_src = new_src.replace(FUNC_ANCHOR, PICK_FUNC + FUNC_ANCHOR, 1)
        changed.append("fetch_models: 精选列表函数（WB_MODEL_PREFIXES / WB_MODEL_SET=official）")
    else:
        print("  [skip] 精选列表函数已是最新版")
    src = new_src

    if MARK4 in src:
        print("  [skip] 未绑定出口的 key 已支持按模型自动选出口")
    else:
        src, n = AUTO_OLD_RE.subn(_auto_realm_sub, src)
        if n:
            changed.append("chat/responses: 未绑定出口的 key 按模型自动选出口 (%d 处)" % n)
        else:
            print("  [warn] 没找到 req_realm 兜底片段，可能上游改了代码 —— 请人工确认", file=sys.stderr)

    # 任务路由：单号 -> 多号依次执行（helper 插在 fetch_models 之前，模块级）
    if TASKS_FUNC.strip() not in src:
        if FUNC_ANCHOR in src:
            src = src.replace(FUNC_ANCHOR, TASKS_FUNC + FUNC_ANCHOR, 1)
            changed.append("tasks: 插入多账号目标选择 helper wb_patch_task_targets")
        else:
            print("  [warn] 没找到 %r 锚点，任务 helper 无法插入" % FUNC_ANCHOR, file=sys.stderr)

    for desc, old, new in (
        ("/tasks 查询: 支持 ?uid=，默认返回所有国内号", OLD_TASKS_GET, NEW_TASKS_GET),
        ("/tasks/run: 依次跑所有国内号", OLD_TASKS_RUN, NEW_TASKS_RUN),
        ("/tasks/travel: 依次对所有国内号执行", OLD_TASKS_TRAVEL, NEW_TASKS_TRAVEL),
    ):
        if new in src:
            print("  [skip] " + desc)
        elif old in src:
            src = src.replace(old, new, 1)
            changed.append(desc)
        else:
            print("  [warn] 没找到目标片段: " + desc + " —— 可能上游改了代码，请人工确认",
                  file=sys.stderr)

    # Key -> 账号白名单（多租户最小形态）
    if TASKS_FUNC_MARK7.strip() not in src:
        if FUNC_ANCHOR in src:
            src = src.replace(FUNC_ANCHOR, TASKS_FUNC_MARK7 + FUNC_ANCHOR, 1)
            changed.append("key-accounts: 插入 wb_patch_key_uids / wb_patch_tenant_session_key")
        else:
            print("  [warn] 没找到 %r 锚点，Key 白名单 helper 无法插入" % FUNC_ANCHOR,
                  file=sys.stderr)

    if NEW_OPEN_SIG in src:
        print("  [skip] open_upstream 已支持 allow 参数")
    elif OLD_OPEN_SIG in src:
        src = src.replace(OLD_OPEN_SIG, NEW_OPEN_SIG, 1)
        changed.append("key-accounts: open_upstream 支持 allow 参数")
    else:
        print("  [warn] 没找到 open_upstream 定义 —— 请人工确认", file=sys.stderr)

    # 冷却收敛（MARK8）：单号白名单被 429 时从 300s 降到 3s
    if NEW_TOTAL_LINE in src:
        print("  [skip] 冷却时长已按白名单收敛")
    elif OLD_TOTAL_LINE in src:
        src = src.replace(OLD_TOTAL_LINE, NEW_TOTAL_LINE, 1)
        changed.append("cooloff: 白名单内可用号数决定冷却（单号=3s）")
    else:
        print("  [warn] 没找到 open_upstream 的 total 计算 —— 冷却收敛未生效，请人工确认",
              file=sys.stderr)

    for desc, old, new in (
        ("key-accounts: 选号不越出白名单", OLD_OPEN_LOOP, NEW_OPEN_LOOP),
        ("key-accounts: /v1/responses 传入白名单", OLD_CALL_RESP, NEW_CALL_RESP),
        ("key-accounts: /v1/chat/completions 传入白名单", OLD_CALL_CHAT, NEW_CALL_CHAT),
        ("key-accounts: 设置回显 accounts", OLD_VIEW_KEY, NEW_VIEW_KEY),
        ("key-accounts: 设置返回账号候选", OLD_VIEW_RET, NEW_VIEW_RET),
        ("key-accounts: 保存接口接受 accounts", OLD_SAVE_ITEM, NEW_SAVE_ITEM),
    ):
        # 账号候选那段后来被 MARK10（别名）改写了，已存在 account_options 就算打过，别报 warn
        if new in src or (old == OLD_VIEW_RET and '"account_options"' in src):
            print("  [skip] " + desc)
        elif old in src:
            src = src.replace(old, new, 1)
            changed.append(desc)
        else:
            print("  [warn] 没找到目标片段: " + desc + " —— 可能上游改了代码，请人工确认",
                  file=sys.stderr)

    # 账号别名（MARK9）：上游昵称不好辨认，允许在面板给账号起个别名
    if "def wb_patch_account_aliases(" in src:
        print("  [skip] 账号别名 helper 已在")
    elif FUNC_ANCHOR in src:
        src = src.replace(FUNC_ANCHOR, ALIAS_PROXY_FUNC + FUNC_ANCHOR, 1)
        changed.append("account-alias: 插入 wb_patch_account_aliases")
    else:
        print("  [warn] 没找到 %r 锚点，账号别名 helper 无法插入" % FUNC_ANCHOR,
              file=sys.stderr)

    for desc, old, new in (
        ("account-alias: /accounts 返回 alias", OLD_ACCOUNT_VIEWS, NEW_ACCOUNT_VIEWS),
        ("account-alias: 看板按账号聚合带 alias", OLD_ACCTS_SORT, NEW_ACCTS_SORT),
        ("account-alias: 设置回显别名表", OLD_VIEW_ALIAS, NEW_VIEW_ALIAS),
        ("account-alias: 保存接口接受 account_aliases", OLD_SAVE_ALIAS, NEW_SAVE_ALIAS),
    ):
        if new in src:
            print("  [skip] " + desc)
        elif old in src:
            src = src.replace(old, new, 1)
            changed.append(desc)
        else:
            print("  [warn] 没找到目标片段: " + desc + " —— 可能上游改了代码，请人工确认",
                  file=sys.stderr)

    # 用量流水增加 API Key 维度（MARK11）
    if "def usage_by_key(" in src:
        print("  [skip] 用量流水 Key 维度已在")
    elif FUNC_ANCHOR in src:
        src = src.replace(FUNC_ANCHOR, USAGE_KEY_FUNC + FUNC_ANCHOR, 1)
        changed.append("usage-key: 插入 wb_patch_set_key / usage_by_key")
    else:
        print("  [warn] 没找到 %r 锚点，Key 维度 helper 无法插入" % FUNC_ANCHOR,
              file=sys.stderr)

    for desc, old, new in (
        ("usage-key: 认出 Key 后记录调用方身份", OLD_KEY_ENTRY_SET, NEW_KEY_ENTRY_SET),
        ("usage-key: 成功请求流水带 key 维度", OLD_RECORD_USAGE, NEW_RECORD_USAGE),
        ("usage-key: 失败请求流水带 key 维度", OLD_RECORD_ERROR, NEW_RECORD_ERROR),
        ("usage-key: 新增 /usage/by-key 路由", OLD_USAGE_ROUTE, NEW_USAGE_ROUTE),
    ):
        if new in src:
            print("  [skip] " + desc)
        elif old in src:
            src = src.replace(old, new, 1)
            changed.append(desc)
        else:
            print("  [warn] 没找到目标片段: " + desc + " —— 可能上游改了代码，请人工确认",
                  file=sys.stderr)

    if NEW_SESSION in src:
        print("  [skip] 会话粘性已隔离到租户维度")
    elif OLD_SESSION in src:
        hits = src.count(OLD_SESSION)
        src = src.replace(OLD_SESSION, NEW_SESSION)
        changed.append("key-accounts: 会话粘性隔离到租户维度 (%d 处)" % hits)
    else:
        print("  [warn] 没找到 extract_session_key 调用点 —— 请人工确认", file=sys.stderr)

    if changed:
        # 备份一次原文件
        bak = SRC + ".orig"
        if not os.path.exists(bak):
            try:
                with io.open(bak, "w", encoding="utf-8") as fh:
                    fh.write(io.open(SRC, encoding="utf-8").read())
            except Exception:
                pass
        with io.open(SRC, "w", encoding="utf-8") as fh:
            fh.write(src)

    for c in changed:
        print("  [ok] " + c)

    # wb_settings.py / dashboard.html 是独立文件（Dockerfile 里 COPY 进镜像），同样需要补
    repo_dir = os.path.dirname(os.path.abspath(SRC))
    patch_settings(os.path.join(repo_dir, "wb_settings.py"))
    patch_dashboard(os.path.join(repo_dir, "dashboard.html"))

    print("  patch done ->", SRC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
