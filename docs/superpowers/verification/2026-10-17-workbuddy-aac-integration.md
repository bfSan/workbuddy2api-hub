# WorkBuddy AAC integration verification

日期：2026-10-17

## 已验证提交

- AAC OAuth persistence: `cda8219f`
- AAC OAuth routes and permissions: `3aba040e`
- WorkBuddy hybrid authentication: `c7eb58a`
- WorkBuddy tenant roots: `10099e3`
- WorkBuddy scoped API keys: `4088a1b`
- WorkBuddy tenant scheduler/usage: `8731fcd`
- WorkBuddy deployment packaging: `9494622`

## AAC focused verification

```text
node --test tests/oauth-persistence.test.mjs tests/oauth-http.test.mjs tests/oauth-permission-mapping.test.mjs tests/auth-behavior.test.mjs tests/storage/auth-contract.test.mjs
30 tests, 30 passed, 0 failed
```

覆盖客户端注册、精确 redirect URI、授权码 hash/过期/重放、PKCE、token claims、introspection、JWKS、`workbuddy:access` 和 `workbuddy:admin`。

## WorkBuddy verification

通过的脚本包括：

- `_test_wb_auth.py`, `_test_hybrid_auth.py`
- `_test_tenant_isolation.py`, `_test_tenant_migration.py`
- `_test_api_key_scope.py`, `_test_route_authorization.py`
- `_test_scheduler_tenant_scope.py`, `_test_usage_tenant_scope.py`
- `_test_e2e_aac_hybrid.py`
- 现有账号、模型、路由、usage、面板和 cooldown 回归脚本

所有上述脚本退出码为 0。`python -m py_compile wb_auth.py wb_tenants.py wb_proxy.py wb_scheduler.py wb_accounts.py wb_settings.py wb_tasks.py scripts/migrate-legacy-tenant.py` 通过，`git diff --check` 通过。

`_test_pagination_browser.py` 未执行成功，因为当前环境没有安装 `playwright`（`ModuleNotFoundError`）；这不是本次改动引入的功能失败。

## 安全与运行前提

- AAC 需要配置 `AAC_BASE_URL`、`AAC_CLIENT_ID`、`AAC_REDIRECT_URI`。
- WorkBuddy 使用 `WB_AUTH_MODE=hybrid`，保留 `/panel/login`、`/panel/logout`、`/panel/password` 和 `--panel-password`。
- 租户根目录使用 `WB_DATA_ROOT`；租户目录 0700，设置/凭证元数据 0600。
- 旧账号必须通过 `scripts/migrate-legacy-tenant.py` 显式绑定 owner；dry-run 只输出脱敏 owner 前缀、文件数和字节数。
- Qoder 没有加入 WorkBuddy 的 Docker/Compose 挂载、OAuth client、配置或数据路径。
- 本阶段仍需在真实 AAC 环境执行两名用户、一个 WorkBuddy admin、一个 local-admin 和一个被禁用用户的浏览器手工验收；当前自动化测试使用脱敏 fixture 用户。

## 上线前阻塞项

当前实现保留旧 `AccountPool` 全局路径作为兼容层，尚未把所有上游请求、settings、usage 和 scheduler 调用全部切换到 `TenantRuntime`；因此不能直接宣称已完成生产级多用户隔离。另一个限制是独立 API Key 请求目前需要先绑定到 tenant directory，尚未实现无会话情况下的全局 tenant-index 查找。两项都应在开启多用户生产模式前补齐。

## 请求级租户隔离补强（2026-10-17）

已补齐此前两个上线前阻塞项的核心路径：

- `TenantRuntime` 懒加载独立 `AccountPool`，并为每个租户提供独立 settings、usage、scheduler 状态目录。
- HTTP 请求通过 `ContextVar` 绑定当前 runtime；`open_upstream()`、账号路由、model/settings/alias、usage 和 scheduler 通过代理读取当前租户对象。
- OAuth 会话按 AAC 用户创建 runtime；无浏览器会话的用户 API Key 先通过 `tenant-index.json` 定位 owner，再加载对应 runtime。
- tenant index 使用 SHA-256 key 指纹，不保存明文 Key；未知 Key、过期 Key、跨租户重复绑定均 fail-closed。
- keep-alive 请求开始时清理上一个请求的身份和 Key 上下文，避免连接复用串租户。

新增/更新验证：

```text
_test_request_runtime.py                         PASS
_test_tenant_isolation.py                        PASS
_test_api_key_scope.py                           PASS
_test_scheduler_tenant_scope.py                 PASS
_test_usage_tenant_scope.py                     PASS
全量 _test_*.py（排除缺少 playwright 的 browser 测试） PASS
python -m py_compile ...                         PASS
git diff --check                                 PASS
```

仍未宣称生产多租户最终完成：真实 AAC 环境的双用户浏览器验收、独立 Key 的端到端 HTTP 验收，以及历史 legacy 数据迁移后的真实凭证轮换仍需上线前执行。
