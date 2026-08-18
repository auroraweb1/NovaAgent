# 阶段 01：产品边界与工程地基

> 状态：已确认
>
> 创建日期：2026-08-17
>
> 适用项目：NovaAgent
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 文档目的

本文是 NovaAgent 从零建设的第一个阶段设计，负责把总体路线中的产品范围、工程约束和最小运行闭环落实为可以编码和验收的工程决策。

本文确认后，才允许创建阶段 01 的工程代码骨架。本文不实现聊天、Agent 循环、工具、记忆或完整 Web 控制台；这些能力分别在后续阶段建设。

本文中的“新系统”均指 NovaAgent，“参考项目”均指只读的 CowAgent。

### 1.1 后续产品范围变更

项目负责人于 2026-08-17 在阶段 04 验收后确认：NovaAgent 后续只使用千问，不再接入豆包或其他第二模型 Provider，也不建设图片、音频、视频等模型多模态任务。阶段 01 已验收的双 Provider 配置属于历史实现事实，不再代表当前产品目标；遗留豆包配置和诊断兼容面由进度矩阵 MOD-06 跟踪清理。

## 2. 阶段目标

阶段 01 结束时，NovaAgent 必须成为一个可以被新开发者安装、检查、启动和测试的空白 Python 工程，并建立后续阶段不能绕过的边界。

本阶段交付以下结果：

- 一个使用 `src/novaagent/` 布局的可安装 Python 包。
- 一个统一的 `pyproject.toml`、开发依赖、锁定策略和本地验证命令。
- 一个可校验的配置模型，明确区分应用配置、Web 配置、Provider 配置和运行时路径。
- 阶段 01 验收时实现千问和豆包的固定 Provider 白名单；后续产品范围已收敛为仅千问。
- 一个只提供管理能力的 CLI，包括版本、帮助、`doctor` 和 Web 服务启动命令；CLI 不提供聊天入口。
- 一个默认绑定本机的 Web 服务骨架，至少提供存活检查、就绪检查和诊断信息。
- 结构化日志、统一错误模型、退出码和密钥脱敏规则。
- 单元测试、集成测试、格式检查和静态检查的统一入口。
- 一份可以在干净环境中复现的安装、检查、启动和验收演示。

## 3. 已确认的产品边界

### 3.1 用户入口

Web 控制台是 NovaAgent 唯一的用户聊天入口。后续阶段的单轮聊天、流式输出、会话管理、工具过程、文件和错误展示都必须通过 Web 控制台及其后端 Web API 完成。

Web 控制台由以下两部分组成：

- Web 页面：负责用户输入、会话展示和事件渲染。
- Web API：负责认证、会话请求、事件流和管理操作。

HTTP API、SSE 或 WebSocket 是 Web 控制台的实现协议，不属于额外的用户通道。

### 3.2 管理入口

CLI 只用于开发和运维，不承担用户聊天职责。允许的 CLI 能力包括：

- 查看版本和帮助。
- 校验配置、运行环境、目录权限和 Provider 配置。
- 启动、停止或查看 Web 服务状态。
- 输出经过脱敏的诊断信息。

CLI 不接受聊天消息，不直接调用模型，不创建用户会话，也不成为终端聊天通道。

### 3.3 模型范围

阶段 01 设计和验收时只保留两个模型 Provider：

| Provider | 角色 | 接入阶段 | 约束 |
| --- | --- | --- | --- |
| 千问 / DashScope | 首个真实 Provider | 阶段 03 | 先完成文本、错误、流式和工具调用基础能力 |
| 豆包 | 原计划的第二个 Provider | 已取消 | 后续范围变更已明确不接入 |

当前产品范围进一步收敛为千问是唯一真实 Provider。以下内容不进入新系统：

- OpenAI、Claude、Gemini、DeepSeek、GLM、Kimi、MiniMax 等其他 Provider。
- 豆包或其他第二模型 Provider。
- 任意自定义 Provider、任意自定义模型端点和运行时动态注册 Provider。
- 图片、音频、视频等模型多模态输入和相关生成任务。
- 为补齐某项能力而引入额外模型服务。

千问文本模型和本地工具链不支持的能力必须返回明确的“不支持”状态，不通过引入其他供应商来满足功能列表。

阶段 01 只建立 Provider 配置模型和白名单校验，不发起真实模型请求，也不要求模型密钥存在。

### 3.4 运行形态

第一阶段以单进程模块化单体为目标：

- 一个 Python 进程负责 Web 服务、配置加载、健康检查和后续应用装配。
- 业务层通过抽象 Port 依赖模型、存储和工具，不直接依赖 SDK。
- 默认绑定 `127.0.0.1`，避免未认证的 Web 服务暴露到局域网或公网。
- 需要远程访问时，必须显式配置监听地址并启用认证；这属于后续 Web 阶段的验收范围。

## 4. 阶段非目标

本阶段不做以下工作：

- 不实现聊天页面、聊天 API、流式模型调用或真实 Provider 请求。
- 不实现 Agent 决策循环、工具注册、Shell、文件编辑、浏览器或 MCP。
- 不实现 SQLite 会话、长期记忆、知识库、Skills、定时任务或多 Agent。
- 不实现第三方即时通信渠道、终端聊天和桌面客户端。
- 不引入 OpenAI、Claude、Gemini 或其他第三方模型适配器。
- 不在配置文件中保存 API 密钥，不把密钥写入日志、测试快照或诊断包。
- 不为了未来功能预先创建大量空目录、空模块或未使用的抽象层。

## 5. 技术决策

以下决策是阶段 01 的实现基线。若实现过程中需要改变决策，必须先更新本文或新增 ADR，再修改代码。

| 编号 | 决策 | 选择 | 原因 |
| --- | --- | --- | --- |
| D01 | Python 版本 | Python `3.12`，支持范围 `>=3.12,<3.14` | 使用稳定的类型、异步和标准库能力，避免过早支持过宽版本范围 |
| D02 | 项目元数据 | PEP 621 `pyproject.toml` | 将项目、依赖、工具配置集中到一个入口 |
| D03 | 环境与锁定 | `uv` 创建环境并生成 `uv.lock` | 安装和 CI 结果可复现，开发命令简单 |
| D04 | Web 服务 | FastAPI + Uvicorn | 提供类型化 HTTP 接口、健康检查和后续 SSE/WebSocket 扩展点 |
| D05 | 数据模型 | Pydantic v2 | 统一配置、请求、错误和诊断数据的校验方式 |
| D06 | Provider HTTP | `httpx`，由 Provider 适配器封装 | 支持超时、连接池、测试替身和异步调用 |
| D07 | 前端范围 | 阶段 01 只保留 Web 服务占位页；完整控制台后续确定前端方案 | 先验证后端生命周期，不提前锁定复杂前端工程 |
| D08 | 配置文件 | TOML；密钥只从环境变量或外部凭据注入 | 人类可读，适合本地配置，避免密钥进入仓库 |
| D09 | 日志 | Python `logging` + 结构化 JSON 格式 | 便于 CLI、Web、Docker 和后续观测系统统一消费 |
| D10 | 质量工具 | Ruff、Pytest、Coverage、Mypy | 提供格式、测试、覆盖率和基础类型检查的明确入口 |

### 5.1 依赖分层

依赖方向固定为：

```text
interfaces / bootstrap
          ↓
application
          ↓
domain
          ↑
infrastructure implements domain ports
```

具体规则如下：

1. `domain` 不导入 FastAPI、Pydantic 的 Web 集成、数据库驱动或千问/豆包 SDK。
2. `application` 只依赖 `domain` 和抽象 Port，不直接构造 Provider 客户端。
3. `infrastructure` 实现 `domain` 定义的 Port，隔离 HTTP、文件系统和第三方 SDK。
4. `interfaces/web` 只负责 HTTP 输入输出、认证边界和事件转发，不实现 Agent 决策。
5. `interfaces/management_cli` 只负责管理用例，不调用聊天应用服务。
6. `bootstrap` 负责配置加载、依赖装配、生命周期和启动，不承载业务规则。
7. CowAgent 兼容逻辑只能放在显式导入或适配边界，不进入核心领域对象。

## 6. 工程目录

阶段 01 创建的最小目录如下；后续阶段只能在设计确认后增加对应模块。

```text
NovaAgent/
├── pyproject.toml
├── uv.lock
├── README.md
├── src/
│   └── novaagent/
│       ├── domain/
│       │   ├── errors.py
│       │   ├── events.py
│       │   ├── messages.py
│       │   ├── ports.py
│       │   └── providers.py
│       ├── application/
│       │   ├── diagnostics/
│       │   └── health/
│       ├── config/
│       │   ├── loader.py
│       │   ├── model.py
│       │   └── paths.py
│       ├── infrastructure/
│       │   ├── logging/
│       │   └── providers/
│       ├── interfaces/
│       │   ├── management_cli/
│       │   └── web/
│       └── bootstrap/
│           ├── container.py
│           └── main.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── end_to_end/
├── docs/
│   └── from-zero/
└── scripts/
    └── verify.sh
```

阶段 01 不创建 `agent/`、`tools/`、`memory/`、`knowledge/`、`skills/` 或具体聊天业务模块。目录的存在必须对应已确认的阶段目标。

## 7. 配置设计

### 7.1 配置来源与优先级

配置按以下顺序合并，优先级从低到高：

1. 程序默认值。
2. 默认配置文件 `~/.novaagent/config.toml`。
3. `NOVAAGENT_CONFIG_FILE` 指定的配置文件。
4. `NOVAAGENT_*` 环境变量。
5. 仅用于本次命令的管理 CLI 参数。

配置加载完成后必须生成不可变的配置对象。运行过程中不允许从全局环境变量再次读取配置，也不允许通过修改模块全局变量改变 Provider 或 Web 行为。

### 7.2 配置结构

阶段 01 支持以下配置区域：

```toml
[app]
environment = "local"
log_level = "INFO"

[web]
host = "127.0.0.1"
port = 8765
auth_mode = "local"

[providers]
default = "qwen"
enabled = ["qwen"]

[providers.qwen]
model = ""

[paths]
data_dir = "~/.novaagent/data"
log_dir = "~/.novaagent/logs"
workspace_dir = "~/.novaagent/workspace"
```

`model` 在阶段 01 可以为空，因为本阶段不发起模型请求；千问模型 ID 已在阶段 03 确定。当前产品只保留千问 Provider。

API 密钥不进入 TOML：

- 千问密钥使用 `DASHSCOPE_API_KEY` 注入。
- 诊断只能报告密钥是否存在及其来源，不得报告密钥值、长度以外的可逆信息或完整环境变量。

### 7.3 配置校验

配置加载器必须在启动前完成以下校验：

- `environment` 只能是 `local`、`test` 或 `production`。
- Web 端口必须是 `1` 到 `65535` 的整数。
- `auth_mode` 只能是 `local` 或 `token`。
- `providers.enabled` 必须且只能为 `qwen`。
- `providers.default` 必须出现在 `providers.enabled` 中。
- 未知顶层字段、未知 Provider 字段和拼写错误的环境变量必须产生可读错误。
- 不允许配置 `openai`、`claude`、`gemini`、`deepseek`、`glm`、`kimi`、`minimax` 或 `custom`。
- 不允许使用任意自定义 Provider URL；官方端点由千问 Adapter 固定管理。
- `production` 环境监听非回环地址时，`auth_mode` 必须为 `token`。
- 路径必须经过展开、绝对化和权限检查，不能因为符号链接或相对路径越过配置边界。

配置错误属于启动失败，必须返回稳定的错误码，并在日志中记录字段路径而不是敏感值。

## 8. 运行时路径与状态归属

代码、设计文档和测试位于项目目录；运行时数据默认位于用户目录下，避免把密钥、会话和日志写进 Git 工作区。

| 内容 | 默认位置 | 所属 | 阶段 01 策略 |
| --- | --- | --- | --- |
| 项目源码和文档 | `/Users/jiaojie/NovaAgent` | 开发项目 | 纳入版本控制 |
| 应用配置 | `~/.novaagent/config.toml` | 进程 | 允许备份，不含密钥 |
| 运行数据 | `~/.novaagent/data` | Agent/应用 | 仅创建路径模型，不创建业务数据库 |
| 工作空间 | `~/.novaagent/workspace` | Agent | 仅校验和记录默认位置 |
| 日志 | `~/.novaagent/logs` | 进程 | 创建目录并应用脱敏策略 |
| 临时文件 | 系统临时目录下的 NovaAgent 专用目录 | 单次进程 | 进程结束后清理，后续阶段细化 |
| API 密钥 | 外部环境或凭据系统 | Provider | 不写入项目和运行时配置文件 |

项目目录、Agent 工作空间、用户会话和临时执行目录必须作为不同字段存在，不能用一个“当前目录”变量代替四种归属。

## 9. Web 服务基础

阶段 01 的 Web 服务只验证生命周期和诊断，不提供聊天能力。

### 9.1 初始端点

| 方法 | 路径 | 目的 | 认证 |
| --- | --- | --- | --- |
| `GET` | `/health/live` | 进程已启动且事件循环可响应 | 本机探针免认证 |
| `GET` | `/health/ready` | 配置已加载、路径可用、依赖已装配 | 本机探针免认证 |
| `GET` | `/api/v1/diagnostics` | 返回脱敏的配置和运行状态 | `token` 模式必须认证 |
| `GET` | `/` | 返回版本和阶段状态占位信息 | `token` 模式必须认证 |

阶段 01 不创建 `/chat`、`/sessions` 或模型调用端点。聊天 API 必须在阶段 03/04 的设计中定义，并直接使用统一的 Domain 消息和事件模型。

### 9.2 监听与认证

- 默认监听 `127.0.0.1:8765`。
- `local` 模式允许本机访问健康端点和占位页。
- 绑定非回环地址时必须启用 `token` 模式。
- Token 从 `NOVAAGENT_WEB_TOKEN` 注入，不写入配置文件和日志。
- 认证失败返回统一错误结构，不泄漏是否存在具体资源。
- CORS、请求大小、反向代理和生产 TLS 在阶段 07/15 设计，不在阶段 01 隐式开放。

### 9.3 错误响应

所有管理 API 使用统一结构：

```json
{
  "error": {
    "code": "configuration_invalid",
    "message": "Configuration validation failed",
    "request_id": "..."
  }
}
```

面向用户的 `message` 必须可理解；详细异常写入脱敏日志，不能把 traceback、API 密钥或完整请求头直接返回给客户端。

## 10. 管理 CLI

CLI 命令名称和职责如下：

| 命令 | 作用 | 是否访问模型 |
| --- | --- | --- |
| `novaagent --version` | 输出版本和构建信息 | 否 |
| `novaagent --help` | 输出命令帮助 | 否 |
| `novaagent doctor` | 检查 Python、配置、目录、端口和 Provider 密钥状态 | 否 |
| `novaagent serve` | 启动 Web 服务 | 否，阶段 01 不调用模型 |
| `novaagent status` | 查询本机 Web 服务状态 | 否 |

`doctor` 的检查结果必须包含通过、警告和失败三种状态，并返回可脚本判断的退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 检查通过 |
| `1` | 配置或环境检查失败 |
| `2` | 命令参数错误 |
| `3` | 服务启动或连接失败 |

CLI 不允许添加 `chat`、`ask`、`message` 等交互命令。后续即使需要本地调试，也应使用测试替身或 Web 控制台，不扩展终端聊天入口。

## 11. 日志、错误与安全

### 11.1 日志字段

结构化日志至少包含：

- 时间戳、级别、事件名称和进程 ID。
- 环境、版本、请求 ID 和启动实例 ID。
- Web 请求的 HTTP 方法、路径、状态码和耗时。
- 配置加载结果、Provider 名称和错误分类。

以下内容禁止进入日志：

- API 密钥、Web Token 和完整 Authorization 头。
- 完整用户消息、模型请求正文和文件内容。
- Cookie、环境变量全集和未经脱敏的异常对象。

### 11.2 错误分类

阶段 01 定义稳定错误类别，后续阶段沿用：

| 错误码 | 适用场景 |
| --- | --- |
| `configuration_invalid` | 配置格式、字段或白名单校验失败 |
| `secret_missing` | 需要 Provider 或 Web Token 时密钥不存在 |
| `path_invalid` | 路径不存在、不可访问或越过边界 |
| `provider_not_allowed` | 配置了非千问/豆包 Provider |
| `web_bind_failed` | Web 地址或端口无法监听 |
| `dependency_unavailable` | 运行依赖或系统能力不可用 |
| `internal_error` | 未分类的内部错误，详细信息只进日志 |

### 11.3 安全边界

- 默认最小权限：阶段 01 不主动访问网络，不执行 Shell，不读取任意工作区文件。
- 配置文件和运行目录按最小权限创建；密钥环境变量只在 Provider 装配处读取。
- 诊断信息使用固定字段白名单，不把完整配置对象序列化返回。
- 路径校验在加载阶段完成一次，在实际使用前仍需再次确认，防止符号链接和并发替换。
- 任何非 Web 用户入口都不得绕过认证、审计和配置校验。

## 12. 测试与质量门禁

### 12.1 测试分层

| 层级 | 目标 | 阶段 01 最小覆盖 |
| --- | --- | --- |
| Unit | 验证纯配置、路径、错误和白名单逻辑 | 合法配置、未知字段、未知 Provider、环境变量覆盖、路径边界 |
| Integration | 验证配置装配、Web 生命周期和 CLI | `live`、`ready`、诊断认证、启动失败和退出码 |
| Contract | 固定后续 Web 和 Provider 的边界 | 健康响应、错误结构、Provider 名称和能力声明模型 |
| End-to-end | 从命令到进程验证最小闭环 | `doctor`、`serve`、健康检查和优雅停止 |

测试必须能在没有千问或豆包密钥的环境中运行。真实 API 不得成为阶段 01 自动测试的前置条件。

### 12.2 统一命令

项目至少提供以下命令，具体脚本名称可在实现时调整，但必须保持等价能力：

```text
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run novaagent doctor --environment test
uv run novaagent serve --environment test
```

服务端到端测试必须使用随机可用端口或测试专用端口，并在结束时释放进程和临时目录。

### 12.3 覆盖目标

- 配置、路径、错误和 Provider 白名单核心逻辑覆盖率不低于 90%。
- Web 健康和诊断端点覆盖正常、未就绪、认证失败和配置失败路径。
- 每个启动失败场景都有稳定退出码和可读错误信息。
- 测试输出不得包含 API 密钥、Token 或完整环境变量。

## 13. 阶段实现顺序

阶段 01 进入编码后按以下顺序实施，每一步都要能独立验证：

1. 创建 `pyproject.toml`、锁定文件、README、包入口和测试入口。
2. 实现版本信息、统一错误类型和退出码。
3. 实现配置模型、配置来源合并和 Provider 白名单。
4. 实现路径解析、目录检查和日志初始化。
5. 实现 Bootstrap 装配容器，确保 Domain 不依赖外部框架。
6. 实现 Web 健康、就绪、诊断和占位页。
7. 实现 `doctor`、`serve`、`status` 和优雅停止。
8. 增加单元、集成、契约和端到端测试。
9. 增加 Ruff、Pytest、覆盖率和本地一键验证配置。
10. 使用干净环境完成安装、诊断、启动、检查和停止演示。

## 14. 阶段验收标准

阶段 01 只有在以下标准全部满足后，才能进入阶段 02：

### 14.1 安装与工程

- 新开发者只依据 README 即可用 `uv` 创建环境并安装项目。
- `src/novaagent/` 包可以被测试和命令行入口导入。
- 锁定依赖后，重复安装得到一致的直接依赖版本。
- Ruff 和 Pytest 命令在干净环境中通过。

### 14.2 配置与范围

- 合法的千问、豆包和 Web 配置可以加载。
- 配置 OpenAI、Claude、Gemini、DeepSeek、GLM、Kimi、MiniMax 或自定义 Provider 时，启动前失败。
- 配置终端聊天、第三方渠道或自定义模型端点时，启动前失败或被明确忽略并给出错误；不能静默启用。
- 密钥缺失只影响需要密钥的诊断项，不阻止阶段 01 的基础健康检查。
- 密钥值、Web Token 和敏感配置不会进入日志、诊断响应或测试输出。

### 14.3 Web 与 CLI

- `novaagent doctor` 能报告 Python、配置、路径、Provider 白名单和 Web 状态。
- `novaagent serve` 默认监听 `127.0.0.1`，能启动并被健康检查访问。
- `/health/live` 和 `/health/ready` 返回稳定 JSON 结构。
- `/api/v1/diagnostics` 按认证模式保护，并只返回脱敏字段。
- CLI 没有聊天命令，Web 是唯一预留的用户入口。
- Web 服务收到停止信号后能释放端口、日志句柄和临时资源。

### 14.4 过程证据

完成报告必须记录：

- 实际 Python、uv、依赖和操作系统版本。
- 安装、格式检查、测试、`doctor`、启动和健康检查命令及结果。
- 至少一次非法 Provider 配置被拒绝的演示。
- 至少一次缺少密钥但基础健康检查仍可运行的演示。
- 与本文设计的偏差、未完成项和进入阶段 02 前必须解决的问题。

## 15. 最小演示脚本

阶段 01 的可复现演示按以下顺序执行：

```text
1. 在干净 Python 3.12 环境创建 uv 环境。
2. 安装锁定依赖。
3. 运行 `novaagent --version`。
4. 运行 `novaagent doctor --environment test`，确认无模型密钥也能完成基础检查。
5. 启动 `novaagent serve --environment test`。
6. 请求 `/health/live` 和 `/health/ready`，确认返回成功。
7. 请求 `/api/v1/diagnostics`，确认字段脱敏。
8. 使用非法 Provider 配置重新运行 `doctor`，确认返回 `provider_not_allowed` 和非零退出码。
9. 发送停止信号，确认端口和临时资源释放。
10. 运行完整测试、格式检查和覆盖率命令。
```

该演示不调用真实模型，不发送用户聊天消息，也不验证后续阶段的模型能力。

## 16. 风险与后续边界

| 风险 | 阶段 01 处理 | 后续阶段 |
| --- | --- | --- |
| 领域层被千问实现细节污染 | 只定义统一 Model Port 和 Provider 配置，暂不实现真实调用 | 阶段 03 验证千问 Adapter；Model Port 继续用于隔离和测试替身 |
| Web 控制台前端方案过早锁定 | 阶段 01 只提供占位页和健康 API | 阶段 03、04、07 决定页面演进 |
| 远程暴露造成未认证访问 | 默认只监听回环地址，非回环地址强制 Token | 阶段 07、15 完善认证和部署 |
| 未来运行数据与项目代码混在一起 | 设计独立 data、workspace、log 和 temp 路径 | 阶段 08、10、15 细化生命周期 |
| 旧 CowAgent 配置污染新领域模型 | 只允许在导入边界转换 | 阶段 08、10、15 分别设计兼容范围 |
| 诊断信息泄露密钥 | 固定字段白名单和脱敏测试 | 所有后续阶段继承 |

阶段 01 不为这些风险预先实现复杂框架；每个风险在对应阶段进入设计时再扩展。

## 17. 决策记录

| 编号 | 决策 | 状态 | 备注 |
| --- | --- | --- | --- |
| D01 | Python `3.12`，支持范围 `>=3.12,<3.14` | 已确认 | 已使用 Python 3.12.13 验证 |
| D02 | 使用 `uv` 和 `uv.lock` | 已确认 | 已生成锁定文件并完成依赖安装 |
| D03 | FastAPI + Uvicorn 作为 Web 基础 | 已确认 | 已完成健康和诊断端点验证 |
| D04 | Web 控制台是唯一聊天入口 | 已确认 | 产品范围决策 |
| D05 | Provider 只允许千问和豆包 | 已被替代 | 阶段 01 历史决策，后续由 D07 替代 |
| D06 | CLI 只做管理和诊断，不做聊天 | 已确认 | 产品范围决策 |
| D07 | 千问是唯一模型 Provider；不建设模型多模态任务 | 已确认 | 2026-08-17 产品范围变更 |

本文设计已确认并完成验收。D01～D04、D06 继续有效，D05 已由 D07 替代；后续变更必须通过本文修订或新增 ADR 记录。
