# WorkBuddy 国内/国际统一账号路由设计

## 1. 背景与目标

当前网关已经能保存国内版和国际版 WorkBuddy 账号，也能为 API Key 绑定出口，但请求路径仍然部分依赖面板维护的 `CURRENT_REALM`。共享模型在没有明确出口时会回落到这个全局状态，账号选择器也只能在单一 realm 内轮询。结果是：客户端需要知道面板状态，`/v1/models` 只能看到一套模型，国内与国际账号不能组成一个统一的出口池。

本设计把数据面改为“单入口、账号决定出口”：客户端只连接一个 OpenAI 兼容入口，网关根据 WorkBuddy 账号凭证识别 `intl` 或 `cn`，再从统一账号池选择正确账号和上游地址。面板 realm 只保留为管理视图和兼容状态，不再决定聊天请求的实际出口。

成功标准：

- 同一个 API Base URL 可以同时服务国内和国际账号。
- 共享模型不需要用户手工切换面板即可选择可用出口。
- 独占模型永远不会被发送到错误区域。
- 同一个会话在没有故障时保持同一出口，降低上下文和风控变化。
- `/v1/models` 默认返回两边模型并集，同时保留旧的 realm 查询兼容性。
- 现有账号文件、API Key、面板配置和旧客户端可以平滑迁移。

## 2. 范围与非目标

本次范围：

- 严格识别账号凭证的 realm。
- 支持跨 realm 的账号选择、会话粘性和有限故障转移。
- 合并国内/国际模型目录和元数据。
- 迁移 API Key 的 realm 语义。
- 更新 usage、错误和面板接口，使实际路由可见。

本次不做：

- 不改变 WorkBuddy 上游协议、设备指纹算法或 OAuth 登录流程。
- 不把原始 WorkBuddy access token 作为客户端网关认证协议推广给所有调用方。
- 不在已经向客户端发送流式数据后重放请求。
- 不删除旧的 `?realm=`、`X-Realm` 或面板管理接口；它们只承担兼容和管理用途。

## 3. 当前实现与问题定位

相关代码集中在 `wb_proxy.py`、`wb_accounts.py`、`wb_settings.py` 和 `wb_catalog.py`。

- `wb_accounts.Account` 已保存 `realm`，并通过 token issuer/domain 推断区域；未知情况目前默认成国际版，需要改为严格识别。
- `AccountPool.pick()`、`pick_for_session()` 都要求单个 realm，因此无法在两个账号池之间选择。
- `Handler._request_realm()` 会读取 Key 绑定、`X-Realm`、查询参数，之后 `open_upstream()` 再回落到 `detect_model_realm()` 和 `CURRENT_REALM`。
- `detect_model_realm()` 对两边都支持的模型返回全局 realm，导致共享模型依赖面板状态。
- `open_upstream()` 以目标 realm 选择账号，URL 再由该账号的 `realm` 拼接；后半段机制可复用，前半段选择逻辑需要改造。
- `/v1/models` 按单个 realm 调用 `fetch_models()`，默认返回 `CURRENT_REALM` 的目录。
- 模型隐藏和排序配置按 `intl`、`cn` 分开保存；静态目录和独占模型集合也按区域散落在代理模块中。

现有回归测试在设计阶段基线通过：模型配置 51 项、账号冷却与轮换 30 项、Key 用量 13 项，核心 Python 文件通过 `py_compile`。

## 4. 设计概览

数据面新增四个清晰的责任边界：

1. **Credential Realm Detector**：从账号凭证识别 `intl`、`cn` 或 `unknown`，并记录识别来源。
2. **Unified Model Registry**：把两套目录合并为一个模型 ID 到区域变体的索引。
3. **Route Planner**：根据模型可用区域、Key 策略、会话粘性和账号健康度生成候选区域顺序。
4. **Upstream Executor**：依次选择账号并发送请求，处理账号级失败、模型级限流和有限重试。

面板和任务系统继续使用 realm 过滤账号。只有聊天、Responses 和公开模型发现走统一数据面。

## 5. 账号 realm 识别

### 5.1 识别输入

对每个账号在加载、导入和刷新后执行同一函数：

```text
detect_account_realm(access_token, domain, stored_realm)
    -> intl | cn | unknown
```

优先级：

1. token 的 `iss`、`aud` 等可信 claim；
2. credential 中的 `domain`；
3. 已保存 realm 仅作为历史兼容信息，不能覆盖明确的 token/domain 证据。

域名映射至少覆盖：

- 国际：`www.workbuddy.ai` 及其 issuer；
- 国内：`copilot.tencent.com`、`codebuddy.cn` 及其 issuer。

### 5.2 冲突和未知处理

- issuer 与 domain 指向不同区域：账号标记 `realm=unknown`，写入 `lastError`，不参与请求。
- 两者都无法识别：同样标记 `unknown`，面板显示“无法识别出口”，要求重新导入或重新登录。
- 已保存的 `realm` 与新 token 证据不一致：以新证据为准并原子保存。
- refresh 后重新识别；如果刷新结果改变 realm，清除该账号的旧 affinity。

`unknown` 账号不能被自动路由器选中，但仍可在面板导出、删除或重新启用。

## 6. 统一账号池与路由策略

### 6.1 API Key 策略

设置中的 Key `realm` 规范化为：

- `auto`：跨区域自动路由；
- `intl`：只允许国际账号；
- `cn`：只允许国内账号。

旧的空字符串和旧版单 Key 字段都迁移为 `auto`。现有 `accounts` 允许列表继续生效；如果允许列表只包含一个区域，自动收窄候选区域。

### 6.2 模型可用区域

模型注册表对每个 ID 计算：

```json
{
  "id": "deepseek-v4.1-flash",
  "realms": ["intl", "cn"],
  "variants": {
    "intl": {"credits": "x0.00", "supportsImages": true},
    "cn": {"credits": "x0.03", "supportsImages": true}
  }
}
```

如果模型只存在于一边，`realms` 只有一个值。模型目录是候选约束，最终是否可请求还要检查账号 readiness。

### 6.3 候选区域排序

`RoutePlanner` 的输入为模型 ID、Key 策略、session key、允许 UID 集合和账号健康快照，输出有序候选：

1. 模型独占区域；若与 Key 硬限制冲突，返回 400。
2. 会话 affinity 命中的区域，前提是仍有可用账号。
3. Key 的硬限制区域；`auto` 不产生硬限制。
4. 允许 UID 所覆盖的区域。
5. 近期失败率更低、未处于模型 cooldown 且 token 剩余时间足够的区域。
6. 另一可用区域作为故障转移候选。

共享模型的首次选择要有稳定的确定性 tie-break，建议使用模型 ID、租户 Key ID 和日期窗口的哈希，避免所有新会话集中到同一地区；健康度只在候选区域明显不可用或进入冷却时改变顺序。

### 6.4 会话粘性

affinity 的值从 `account UID` 扩展为 `{realm, uid}`。绑定键必须继续包含 API Key/租户命名空间，避免不同客户端共用同一会话 ID 时串账号。

当绑定账号不可用时：

- 先在同 realm 选择另一个账号；
- 同 realm 无可用账号时，若模型和 Key 允许，切换到另一 realm；
- 新账号成功后更新 affinity。

### 6.5 重试边界

- 401/403：账号级失败，冷却账号并换账号。
- 429：记录“账号 + 模型”冷却，先换同区域账号，再尝试另一候选区域。
- DNS、TLS、连接重置和 5xx：按现有网络重试策略处理；跨区域切换最多一次。
- 已向客户端写出任何流式数据后，不重试、不切换，避免重复输出。
- 非流式请求只在请求体可安全重放时重试；记录 `retry_count` 和 `route_failover=true`。

## 7. 统一模型注册表

### 7.1 数据来源

国内和国际仍分别执行上游同步、产品缓存读取和静态目录回退。同步结果写入现有持久化缓存时增加统一索引层，不改变旧的按 realm 快照格式。

### 7.2 合并规则

- 同 ID 模型合并为一个公开模型。
- 公共字段使用优先级明确的合并规则：上游实时元数据 > 持久化快照 > 静态目录。
- 区域差异保存到 `variants` 或扩展字段，不用一边的数据覆盖另一边。
- 隐藏和排序保留现有 realm 配置；统一列表使用两个区域的顺序合并，并确保手工顺序优先。
- `/v1/models` 默认返回所有当前至少有一个可用变体的模型；没有账号时可返回最近缓存目录，但在响应中标记 `available=false`。

### 7.3 兼容接口

- `/v1/models`：返回并集，响应增加非标准字段 `x_workbuddy.realms`、`x_workbuddy.variants`。
- `/v1/models?realm=intl|cn`：返回指定区域目录，供旧客户端和面板继续使用。
- `/settings/models`、`/models/sync`：仍按 realm 操作，并额外返回统一摘要。
- `/realm`：保留 `current` 字段，但说明它是面板视图状态，不代表 API 数据面出口。

## 8. 配置和迁移

启动时执行一次无破坏迁移：

1. 旧 `api_key/api_key_set` 转成一条 `realm=auto` 的 Key。
2. `api_keys` 中空 realm 转成 `auto`。
3. 账号文件补齐 `realmSource`、`realmError` 等识别元数据；不删除旧字段。
4. 保留 `active_realm.json`，但新的聊天请求不再读取它。
5. 面板文案将“切换网关上游”改为“管理视图区域”；旧按钮调用仍可返回成功，避免旧前端报错。

配置写入采用临时文件 + `os.replace`，保持现有原子写入习惯。

## 9. 错误、观测和安全

新增可操作错误：

- `unknown account realm`：账号凭证无法判断区域；
- `model unavailable in configured realms`：模型存在但 Key/账号策略不允许；
- `no usable account across realms`：两边账号都不可用；
- `model/realm conflict`：独占模型与 Key 硬限制冲突。

每条 usage/error 记录增加：

- `requested_model`、`resolved_model`；
- `selected_realm`、`selected_account`；
- `route_reason`（exclusive、affinity、health、failover）；
- `retry_count`、`failover`。

日志不能记录 access token、refresh token 或完整 Authorization header。面板可显示 realm、账号昵称、失败原因和冷却时间，但不显示凭证。

## 10. 测试策略

新增纯函数测试：

- issuer/domain 正确识别国内、国际、未知和冲突凭证；
- refresh 后 realm 变更会清理 affinity；
- 共享模型在两边账号可用时生成稳定候选顺序；
- 独占模型只生成唯一候选区域；
- Key `auto`、`intl`、`cn` 和账号允许列表组合正确收窄；
- 同区域账号耗尽后跨区域故障转移；
- 429 只冷却模型/账号组合，401/403 冷却账号；
- 流式首帧后不重试；
- `/v1/models` 并集、区域过滤和旧配置迁移；
- usage 记录真实 realm，而不是 `CURRENT_REALM`。

保留现有 `_test_model_config.py`、`_test_model_cooldown.py` 和 `_test_usage_key.py`，并增加混合账号池的端到端假上游测试。每次变更执行 `py_compile`、全部 Python 回归测试以及模型目录 JavaScript 测试。

## 11. 分阶段交付

### 阶段 A：识别和纯路由模型

- 抽出 realm detector、模型 registry 和 route planner，先不改变真实请求。
- 用测试固定旧配置迁移和候选排序。

### 阶段 B：统一账号选择

- 增加跨 realm 账号快照和 `{realm, uid}` affinity。
- 改造 `open_upstream()`，让账号决定 URL。
- 增加账号级和模型级跨区域故障转移。

### 阶段 C：统一模型发现

- `/v1/models` 默认返回并集。
- 同步和缓存加入统一摘要及区域变体。
- 面板改为视图筛选，不再宣称切换网关出口。

### 阶段 D：观测和灰度

- 增加 route reason、failover 和真实 realm 指标。
- 提供环境变量或启动开关，以便在出现上游差异时临时关闭跨区域 failover。
- 在混合账号池上执行回归和长时间稳定性观察后，再默认打开全部自动路由。

## 12. 主要风险与取舍

- 同名模型在国内和国际的系统提示、倍率或能力可能不同；统一列表必须保留变体信息，不能假设完全等价。
- 跨区域 failover 可能改变计费区域和响应风格，因此 usage 必须记录实际区域，并允许 Key 关闭跨区域切换。
- 共享模型的首次选择会影响长期会话；会话 affinity 和确定性 tie-break 是稳定性的必要条件。
- 错误账号凭证不能“试发”到两个区域探测，必须先完成 issuer/domain 识别。
- 面板和 API 语义分离后，旧用户可能误以为 `/realm` 仍控制请求，需要在接口响应和 UI 文案中明确说明。

