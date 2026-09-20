# WorkBuddy2API-Hub — 国际版、国内版多账号网关中枢

<p align="center">
  <a href="https://github.com/ardeyouxipianyi/workbuddy2api-hub/releases"><img src="https://img.shields.io/badge/Release-v1.2.0-2496ED?style=flat-square" alt="Version 1.2.0"></a>
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/API-OpenAI_Compatible-412991?style=flat-square" alt="OpenAI API">
  <img src="https://img.shields.io/badge/Dual_Realm-Intl_&_CN-0DBD8B?style=flat-square" alt="Dual Realm">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Vibe_Coding-100%25-ff69b4?style=flat-square" alt="Vibe Coding">
</p>

本项目为 **WorkBuddy2API-Hub**，将腾讯 **[www.workbuddy.ai](https://www.workbuddy.ai)** (国际版) 与 **[codebuddy.cn](https://www.codebuddy.cn)** (国内版) 原生服务封装为标准 OpenAI 兼容接口，支持 Chat Completions 与 Responses API。具备多账号负载轮询、稳定物理设备指纹隔离、OAuth 一键免客户端登录、国内版每日签到与实时积分查询、国内成长任务全自动完成与国内版积分任务、后台常驻定时调度器、Web 监控看板等全套能力。

- **开箱即用**：绿色包自带精简 Python ，双击批处理脚本即启。
- **双区域独立路由**：支持 🌐 国际版 与 🇨🇳 国内版独立配置与管理，严格隔离串号，看板一键切换且状态落盘持久化。
- **模型列表严格按照桌面应用 1:1 对齐**：按官方桌面端主界面清洗收敛，彻底剔除内部代码补全通道与底层专线变体。
- **模型列表可在看板配置**：支持从上游强制同步、隐藏/恢复、手工排序；新增模型默认合并进全量池，受当前环境过滤的模型不会重新露出。
- **最近请求独立页面**：请求明细从网关首页拆到独立 Tab，默认展示最近 200 条，可仅看失败。
- **API Key 维度指标**：按 Key 聚合请求、成功率、Token、缓存命中、TTFT、速度与积分；埋点前的历史行仅保留在账号/原始流水视图中。
- **稳定物理设备指纹隔离 (`derive_id`)**：国际版与国内版统一方案，以账号自身 UID 稳定哈希派生专属机器特征与会话标识，同一账号长期固定在一台虚拟物理设备上，天然防多号关联风控。
- **OAuth 一键免客户端登录**：无需在本地安装桌面客户端，点击看板链接在浏览器完成授权即可自动入库；亦支持扫描本地客户端两步确认导入。
- **国内版签到与实时积分查询**：支持国内版每日签到领积分，实时聚合账户资源包用量与余额。
- **国内成长任务与积分任务全自动完成**：全自动接取任务、构造行为事件上报点亮并自动领取奖励，支持猫猫日常旅行与连续打卡。
- **后台常驻定时调度器**：每日整点排程（09:00/21:00 签到与猫猫派出/领奖 · 22:00 保活 · 01:00 夜猫），国际版自适应为专属 Token 集中保活。
- **双协议全功能支持**：同时支持标准 OpenAI Chat Completions 协议与 Responses API (Codex / Claude Code)。
- **现代化 Web 看板**：单行自适应弹性指标卡片、模型性能指标与用量一览融合大表、实时请求流水监控。

> ⚡ **Vibe Coding 产物**：本项目为 100% Vibe Coding 协同产物，由人类开发者提出架构与业务意图，AI 助手端到端完成逆向分析、链路调度、WAF 指纹脱敏与界面编写。

---

## 一、快速启动

### 1. 本机单机使用
双击运行 **`start-wb-proxy.bat`**，保持窗口运行：
- **API 接口地址**：`http://127.0.0.1:8788/v1`
- **Web 监控看板**：`http://127.0.0.1:8788/`

首次启动若无账号，直接打开看板点击 **「+ 添加账号 (OAuth)」**，在浏览器完成授权即可自动加入。

### 2. 面板访问密码

打开看板需要先输入**面板访问密码**，默认是 `admin`。它与 API Key 相互独立：

- 面板密码只用于打开网页看板，可在看板的「设置」页随时修改（也可启动时用 `--panel-password` 指定）；
- 密码以 PBKDF2-SHA256 摘要形式保存在 `accounts/settings.json`，不存明文；
- 登录状态存放在浏览器会话中，关闭浏览器或重启网关后需要重新输入。

> 首次登录后请立即到「设置」修改默认密码。

### 3. 局域网共享模式
双击运行 **`start-wb-proxy-lan.bat`**，允许局域网内其他设备（手机、平板、协同电脑）访问：
- **Base URL**：`http://<本机局域网IP>:8788/v1`
- **密钥随机生成并持久化**：LAN 模式不会使用任何写死的默认密钥。首次启动时自动生成一个高强度随机 API Key，保存到 `accounts/settings.json`，并在终端打印；之后重启会复用同一个 Key（不会每次变化）。
- **自定义 Key**：启动脚本支持第二个参数传入自己的 Key，例如 `start-wb-proxy-lan.bat 8788 我的Key`，此时以你传入的为准。
- 支持带密钥直达面板：`http://<IP>:8788/?key=生成的Key`。

---

### 4. 多 API Key 管理与出口绑定 

网关支持**多 API Key 并行管理**，并可为每个 Key 指定独立出口。不同客户端使用各自绑定的 Key，国内/国外流量互不干扰，完全无需在看板上手动频繁切换网关全局出口：

在 Web 看板的「设置」页面中进行管理：
- **添加与在线生成**：输入 Key 名称，点击「生成随机 Key」即可一键生成高强度密钥，支持随时复制；
- **出口自由绑定**：
  - **🌐 国际版出口**：该 Key 的调用流量强制固定走腾讯国际版官方出口（`www.workbuddy.ai`）；
  - **🇨🇳 国内版出口**：该 Key 的调用流量强制固定走腾讯国内版官方出口（`copilot.tencent.com`）；
  - **跟随面板切换**：未绑定特定出口的 Key，请求将实时跟随看板顶部的全局出口开关分流。
- **状态管理**：可单独开启/停用某个 Key，支持一键删除，删除即刻失效；
- **配置持久化**：所有 Key 均保存在本地 `accounts/settings.json` 中，重启保持生效；
- **安全防冲突机制**：一旦在面板配置保存过 API Key，启动命令或脚本中的旧参数（如 `--api-key`）会自动失效，彻底避免旧密钥在后台漏网继续使用；
- **模型区域自检防护**：当某个 Key 绑定的出口与其请求的模型不匹配时（例如用国际版 Key 去调国内独占的 `deepseek-v4-pro`），网关会直接返回通俗易懂的 400 校验错误，杜绝上游 WAF 晦涩的拒流报错。

### 5. Docker 容器化部署 
自带完整容器配置，零外部依赖，极速启动：

```bash
# 1. 后台启动容器 (自动构建并运行)
docker compose up -d

# 2. 查看网关日志
docker compose logs -f
```

亦可直接使用 `docker run` 启动：
```bash
docker run -d   --name wb-proxy   --restart unless-stopped   -p 8788:8788   -v $(pwd)/accounts:/app/accounts   -v $(pwd)/usage:/app/usage   -e API_KEY=your_secret_key   $(docker build -q .)
```

- **持久化目录**：`./accounts` (账号凭证及活动区域) 与 `./usage` (请求流水与指标快照)；
- **配置参数**：通过环境变量 `API_KEY`、`PORT` 自定义。

### 6. 本地打包与生产部署（推荐）

生产环境采用「本地构建镜像，服务器只部署」的方式。服务器上不再直接拉取源码或执行构建，账号与用量数据始终留在服务器的持久化目录中。

本机先执行打包：

```bash
scripts/package-image.sh
```

脚本会依次运行回归测试、构建 `linux/arm64` 镜像，并输出：

- `dist/workbuddy2api-hub-linux-arm64.tar.gz`：可直接加载的镜像归档；
- `dist/workbuddy2api-hub-linux-arm64.metadata.json`：镜像 ID、SHA256、Git commit 与构建时间。

打包脚本默认使用 `mirror.gcr.io/library/python:3.11-alpine`，避免 Docker Hub 在某些网络环境下不可达。需要严格使用官方镜像时，可覆盖为：

```bash
BASE_IMAGE=python:3.11-alpine scripts/package-image.sh
```

基础镜像只参与本机构建，最终部署使用导出的完整镜像归档，因此生产服务器不需要访问该镜像源。

打包脚本首次运行时会自动在仓库根目录创建 `.venv`，后续测试与打包命令都在这个虚拟环境中执行。项目运行本身仍然只依赖 Python 标准库，`requirements-packaging.txt` 目前只用于固定后续打包工具链的入口。

部署到生产 Podman 主机：

```bash
scripts/deploy-production.sh
```

默认目标为 `yunxing@10.88.86.106`，远端 Podman 路径为 `/opt/podman/bin/podman`，容器名为 `wb-proxy`。部署脚本会保留 `accounts`、`usage` 和模型缓存挂载，只有新容器通过 `/health` 与面板模型接口校验后才算成功；如果启动或校验失败，会自动用旧镜像回滚。

首次在新机器上部署时，可复制 `scripts/deploy-production.sh` 顶部的环境变量说明，创建 `~/.config/workbuddy2api-hub/deploy.env` 覆盖 `REMOTE_HOST`、`REMOTE_USER`、`REMOTE_BASE` 或 `IMAGE`。SSH 密码不会写入仓库，可通过 `SSH_PASSWORD_FILE` 指向本机密码文件；未设置时会兼容读取 `/tmp/sshpw`。

---

## 二、核心特性详解

### 1. 模型列表严格按照桌面应用 1:1 对齐
针对官方本地配置清单（50+ 底层模型）进行了深度清洗，剔除行内代码补全专用模型（如 `codewise-*`、`completion-gf`、`hunyuan-3b/7b`）与底层多云专线变体（如 `*-volc`、`*-lkeap`），严格对齐官方桌面端主界面：

* **🌐 国际版 (16 个)**：`deepseek-v4.1-flash`、`gpt-6-astra`、`hy4-preview-f`、`hy4-preview`、`hy3`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.5`、`gpt-5.4`、`gpt-5.3-codex`、`gemini-3.5-flash`、`glm-5.3`、`glm-5.2`、`kimi-k3`、`kimi-k2.6`。
* **🇨🇳 国内版 (14 个)**：`hy4-preview-f`、`hy3`、`deepseek-v4.1-flash`、`deepseek-v4-pro`、`glm-5.3`、`glm-5.3-flash`、`glm-5.2`、`glm-5.1`、`glm-5v-turbo`、`minimax-m3`、`kimi-k3-1`、`kimi-k2.8-preview`、`kimi-k2.7`、`kimi-k2.6`。

每个模型均宣告完整桌面软件中显示的上下文窗口（K/M 规范）、单次最大输出、视觉支持、工具调用以及推理档位。

> 💡 **关于同模型跨区域混合轮询的说明**：
> 目前对于同时存在于国内版和国际版的同名模型（如 `deepseek-v4.1-flash` 等），**暂未实现跨国内/国际账号的自动混合轮询**，而是作为两个独立区域分别配置与调度，请求只能走当前所选网关的独立出口。这主要是出于各区域网络环境隔离、出站指纹对齐与账号防风控安全考量；待作者后续实测验证确认长期使用稳定且无封号风险后，会尽快跟进并补齐同名模型的跨区域混合轮询能力。

### 2. 稳定物理设备指纹隔离 (`derive_id`)
国际版与国内版统一采用相同的底层算法内核：以账号自身的 UID 结合固定业务盐值单向哈希派生出固定的机器码与会话标识：

- **同一账号长期稳定**：每次出站请求固定来自同一台虚拟个人物理设备，彻底规避机器码随机漂移风控；
- **多账号天然隔离**：不同账号之间机器码与会话彼此独立，彻底阻断跨账号关联风控检测。

### 3. 国内版每日签到、成长任务与积分任务全自动完成
集成官方成长中心全套自动化完成引擎：

- **每日签到**：一键完成国内版每日打卡领取日常积分；
- **成长任务与积分任务**：自动批量接取未接任务，构造真实规范行为事件上报点亮（画布创建、灵感案例、模板使用、模型体验、多轮对话等 14 项任务），并自动调用端点领奖入账；
- **猫猫日常**：空闲时自动派出猫猫旅行，归来产生待领奖励时自动领取。

### 4. 后台常驻定时调度器 (Scheduler)
常驻后台，每日按固定整点执行自动化运维排程：

- **每日 09:00 & 21:00**：国内版账号自动签到，并派出猫猫或领取归来奖励；
- **每日 22:00**：集中扫描全库账号，Token 剩余寿命不足 2 小时自动调用 Refresh Token 保活；
- **每日 01:00**：深夜时段自动执行夜猫子任务；
- **国际版动态自适应**：切换至国际版视图时，调度器自动隐藏签到/猫猫逻辑，专职执行 Token 自动保活与凭证常驻。

---

## 三、账号添加与管理

打开看板 `http://127.0.0.1:8788/`，在「账号」区域操作：

### 方式一：浏览器 OAuth 授权（推荐，免客户端）
1. 点击 **「+ 添加账号 (OAuth)」**；
2. 选择要登录的区域（国际版 / 国内版），点击弹出的官方授权链接并在浏览器完成登录；
3. 程序自动检测回调，完成后账号自动加入账号池，无需手动复制凭证。

### 方式二：从本地桌面应用导入（两步确认）
1. 点击 **「📥 扫描桌面客户端账号」**；
2. 弹窗只读展示本机检测到的桌面客户端账号（昵称、区域、域名、有效期）；
3. 确认无误后点击该行对应的 **「导入」** 按钮，国际版账号自动归入国际版列表，国内版账号自动归入国内版列表。

---

## 四、客户端配置与接入

### OpenAI 兼容客户端 (Chatbox / NextChat / Cherry Studio / Kelivo 等)
- **API 接口地址 (Base URL)**：`http://127.0.0.1:8788/v1`（局域网为 `http://<局域网IP>:8788/v1`）
- **API Key**：
  - 本机单机模式（未配置 Key 且未开 LAN）：可留空或填任意字符；
  - 已在看板配置 Key 或 LAN 模式：在看板「设置」页面添加或复制已绑好出口的 API Key（如固定走国际版的 Key 或国内版的 Key）。
- **模型名称**：填入 `/v1/models` 中列出的任意官方对齐模型 ID（如 `deepseek-v4.1-flash`、`gpt-6-astra`、`glm-5.3` 等）

### Codex CLI / Claude Code (Responses API)
网关原生内置 Responses 协议双向转换与 WAF 指纹脱敏：
```bash
export OPENAI_BASE_URL="http://127.0.0.1:8788/v1"
export OPENAI_API_KEY="你在看板设置中添加并绑定的API_Key"
```

---

## 五、看板与接口一览

访问 `http://127.0.0.1:8788/` 即可使用集成看板，核心接口包括：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | Web 用量与任务监控看板 |
| POST | /v1/chat/completions | 标准 Chat Completions 接口 |
| POST | /v1/responses | Responses API 协议接口 |
| GET | /v1/models | 官方对齐模型列表（含能力与规格宣告） |
| GET | /settings/models | 模型全量池、当前可见集合、隐藏项与顺序（面板会话） |
| POST | /models/sync | 从上游强制同步模型并保存显隐/顺序（面板会话） |
| GET | /tasks | 国内版成长任务、连续打卡与猫猫日常状态 |
| POST | /tasks/run | 触发国内成长任务全自动点亮与领奖 |
| POST | /tasks/travel | 触发猫猫日常旅行（派出 / 领奖） |
| GET | /scheduler | 定时调度器运行状态与排程日志 |
| POST | /scheduler/trigger | 手动立即执行后台巡检保活 |

---

## 六、致谢与引用声明 (Credits & References)

本项目在协议兼容、风控规避与任务链路设计过程中，深度参考并吸纳了开源社区现有项目的经验与逆向成果，特此致谢：

- **[Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)**：
  - **成长任务全链路逆向**：参考了其对腾讯成长任务中心（任务列表、接取、事件上报、领奖端点）的逆向分析与点亮逻辑；
  - **设备指纹稳定派生设计 (`derive_id`)**：吸纳了其以账号 UID 稳定哈希派生固定设备码的思路，有效解决多号防关联风控；
  - **整点排程调度理念 (`Scheduler`)**：参考了其采用每日固定整点排程模拟真人打卡的设计思路；
  - **指纹脱敏管线设计与 DeepSeek 多轮思维链回填**：吸纳了其过滤系统敏感指令与回填 `reasoning_content` 的实践。
- **[CangShui/workbuddy-cliproxy-fix](https://github.com/CangShui/workbuddy-cliproxy-fix)**：
  - 提供了早期关于 WorkBuddy 客户端代理修复与接口差异的参考。
- **[lovingfish/workbuddy-cliproxy](https://github.com/lovingfish/workbuddy-cliproxy)** 与 **[mmqz/cpa-multi-plugins](https://github.com/mmqz/cpa-multi-plugins)**：
  - 提供了关于网关通信与多插件管理的原型参考。
- **[ardeyouxipianyi/workbuddy2api](https://github.com/ardeyouxipianyi/workbuddy2api)**：
  - 提供了国内版分发包逆向分析与出站 User-Agent 规范参考。
- **[@ddddd-ren](https://github.com/ddddd-ren)**：
  - **用量日志高性能倒序检索与看板防堆叠**（PR #14）：实现倒序分块 Seek 读取日志末尾数据，TTL 内存缓存化高频聚合接口，彻底消除大文件（20MB+ / 45k+ 行）下前端看板 60 秒超时与 GIL 卡死问题；
  - **原子写入与并发竞争修复**（PR #13）：消除多线程重写用量摘要文件时的 `ENOENT` 异常与临时文件残留；
  - **账号池 JSON 导出/导入支持**（PR #5）：实现了全量/单账号导出与 Dry-Run 安全导入机制。
- **[@wylftw0314-glitch](https://github.com/wylftw0314-glitch)**：
  - **Responses API custom 工具协议双向转译**（PR #12）：出站降级与入站重构还原 freeform 工具调用，彻底解决 Codex CLI (`apply_patch`) 工具调用静默失效问题，并补充了完整单元测试。

---

## 七、免责声明 (Disclaimer)

1. 本项目为非官方自托管网关，仅供技术研究、逆向协议学习与个人合法授权账号在私有环境测试使用。
2. 本项目不提供任何账号及额度。请严格遵守官方服务条款，禁止用于任何商业转售、恶意并发或违规滥用。
