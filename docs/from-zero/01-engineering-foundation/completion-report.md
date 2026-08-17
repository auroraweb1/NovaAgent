# 阶段 01 完成报告：产品边界与工程地基

> 状态：待验收
>
> 创建日期：2026-08-17
>
> 设计文档：[design.md](./design.md)
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 报告目的

本文记录阶段 01 的实际实现、自动化测试、运行演示、设计偏差和遗留事项。报告用于判断 NovaAgent 是否具备进入阶段 02“核心消息与事件协议”的条件。

本报告不代表已经进入阶段 02，也不代表聊天、模型调用、工具、会话或完整 Web 控制台已经完成。阶段 01 只建立这些后续能力必须依赖的工程基础。

## 2. 阶段结论

阶段 01 的核心工程闭环已经实现并通过基础验证：

- 项目可以使用 Python 3.12 和 `uv` 安装。
- `src/novaagent/` 包、管理 CLI 和 Web 服务可以启动。
- 配置模型只允许千问和豆包 Provider。
- Web 服务提供存活、就绪和脱敏诊断端点。
- CLI 只提供版本、诊断、启动和状态命令，不提供聊天入口。
- 24 个自动化测试通过，Ruff、格式检查和 Mypy 通过。
- GitHub Actions CI 已配置，在推送和拉取请求时执行锁定安装、测试、覆盖率和全部质量检查。
- 真实本地 Web 进程已经启动，并完成健康端点访问和停止验证。

关键验收状态如下：

1. 核心配置模块的覆盖率目标已经达到：配置加载器、配置模型和路径模块分别为 98%、97% 和 100%；当前全项目总覆盖率为 85%。
2. CI workflow 已实现并通过等价的本地命令验证，首次推送后仍需确认 GitHub Actions 远端运行结果。
3. 测试使用的 FastAPI/Starlette `TestClient` 发出一个上游弃用警告，需要在后续依赖升级或测试客户端方案确定后处理。

## 3. 已交付内容

### 3.1 项目和依赖

| 交付物 | 位置 | 结果 |
| --- | --- | --- |
| PEP 621 项目元数据 | [`pyproject.toml`](../../../pyproject.toml) | 已完成 |
| 可复现依赖锁定 | [`uv.lock`](../../../uv.lock) | 已生成 |
| 项目使用说明 | [`README.md`](../../../README.md) | 已完成 |
| Git 忽略规则 | [`.gitignore`](../../../.gitignore) | 已完成 |
| 统一本地验证脚本 | [`scripts/verify.sh`](../../../scripts/verify.sh) | 已完成 |
| GitHub Actions CI | [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) | 已完成 |

项目要求 Python `>=3.12,<3.14`，使用 `uv` 管理环境，运行时和开发依赖分别包含 FastAPI、Uvicorn、Pydantic、HTTPX、Pytest、Ruff、Mypy 和覆盖率工具。

### 3.2 配置和 Provider 边界

实现位置：

- [`config/model.py`](../../../src/novaagent/config/model.py)
- [`config/loader.py`](../../../src/novaagent/config/loader.py)
- [`config/paths.py`](../../../src/novaagent/config/paths.py)
- [`domain/providers.py`](../../../src/novaagent/domain/providers.py)

已实现：

- TOML 配置读取和默认配置路径。
- `NOVAAGENT_*` 环境变量覆盖。
- 未知 NovaAgent 环境变量拒绝。
- `qwen` 和 `doubao` Provider 白名单。
- 未知 Provider、自定义 Provider 和自定义端点拒绝。
- Provider 默认值和启用列表一致性校验。
- 非回环 Web 地址必须启用 Token 认证。
- 配置对象冻结，Provider 启用列表使用不可变元组。
- 数据、日志和工作空间路径展开、绝对化和根目录保护。
- 配置错误映射为稳定的错误码和字段路径。

阶段 01 不读取或发送真实模型请求；千问和豆包的实际 HTTP 适配分别留给阶段 03 和阶段 14。

### 3.3 Web 服务基础

实现位置：

- [`interfaces/web/app.py`](../../../src/novaagent/interfaces/web/app.py)
- [`application/health/service.py`](../../../src/novaagent/application/health/service.py)
- [`application/diagnostics/service.py`](../../../src/novaagent/application/diagnostics/service.py)
- [`bootstrap/container.py`](../../../src/novaagent/bootstrap/container.py)

已提供：

| 方法 | 路径 | 结果 |
| --- | --- | --- |
| `GET` | `/health/live` | 返回进程存活状态 |
| `GET` | `/health/ready` | 创建并检查运行目录后返回就绪状态 |
| `GET` | `/api/v1/diagnostics` | 返回脱敏运行、配置和 Provider 状态 |
| `GET` | `/` | 返回阶段状态占位信息 |

已实现本机默认监听、非回环地址 Token 强制、Bearer 或自定义 Header 认证、请求 ID 响应头和统一错误结构。

阶段 01 没有 `/chat`、`/sessions` 或模型调用端点，符合设计中的阶段边界。

### 3.4 管理 CLI

实现位置：[`interfaces/management_cli/main.py`](../../../src/novaagent/interfaces/management_cli/main.py)

| 命令 | 结果 |
| --- | --- |
| `novaagent --version` | 输出 `0.1.0` |
| `novaagent doctor` | 检查配置、路径、Web 和 Provider 密钥状态 |
| `novaagent serve` | 启动 Web 服务 |
| `novaagent status` | 请求本机就绪端点 |

CLI 没有 `chat`、`ask` 或 `message` 命令。缺少模型密钥时，`doctor` 返回成功并给出警告，不阻止阶段 01 的基础检查。

### 3.5 日志和错误

实现位置：

- [`infrastructure/logging/setup.py`](../../../src/novaagent/infrastructure/logging/setup.py)
- [`domain/errors.py`](../../../src/novaagent/domain/errors.py)

已实现结构化 JSON 日志、事件字段、请求 ID支持和基础敏感标记脱敏；已定义配置无效、密钥缺失、路径无效、Provider 不允许、Web 绑定失败、依赖不可用和内部错误等稳定错误码。

### 3.6 测试

测试位置：

- [`tests/unit/test_config.py`](../../../tests/unit/test_config.py)
- [`tests/integration/test_web.py`](../../../tests/integration/test_web.py)
- [`tests/contract/test_contracts.py`](../../../tests/contract/test_contracts.py)
- [`tests/end_to_end/test_cli.py`](../../../tests/end_to_end/test_cli.py)

已覆盖：

- 默认配置和环境变量覆盖。
- 未知 Provider、未知环境变量和非法路径拒绝。
- 非回环 Web 地址认证要求。
- Web 存活、就绪、诊断和占位页。
- Token 认证成功与失败。
- Provider 白名单契约。
- 缺少模型密钥时 `doctor` 的成功和警告行为。

## 4. 验证证据

以下命令均在项目根目录执行，使用 Python `3.12.13` 和 `uv` 环境。

### 4.1 依赖安装

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv sync --all-groups --python /Users/jiaojie/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12
```

结果：依赖解析、项目构建和安装成功，生成 `.venv` 和 `uv.lock`。

### 4.2 自动化验证

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run pytest
```

结果：`24 passed`。测试过程中出现一个 Starlette/TestClient 上游弃用警告，无测试失败。

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff check .
```

结果：`All checks passed!`

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff format --check .
```

结果：所有文件格式通过。

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run mypy src tests
```

结果：`Success: no issues found in 33 source files`。

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run pytest --cov=novaagent --cov-report=term-missing
```

结果：24 个测试通过，总覆盖率 85%。配置加载器 98%，配置模型 97%，路径模块 100%；核心配置逻辑已达到设计要求的 90% 目标。

### 4.3 CLI 验证

```text
NOVAAGENT_DATA_DIR=/private/tmp/novaagent-data \
NOVAAGENT_LOG_DIR=/private/tmp/novaagent-logs \
NOVAAGENT_WORKSPACE_DIR=/private/tmp/novaagent-workspace \
uv run novaagent --version
```

结果：`0.1.0`。

```text
NOVAAGENT_DATA_DIR=/private/tmp/novaagent-data \
NOVAAGENT_LOG_DIR=/private/tmp/novaagent-logs \
NOVAAGENT_WORKSPACE_DIR=/private/tmp/novaagent-workspace \
uv run novaagent doctor --environment test
```

结果：返回 `status: ok`；千问和豆包均被识别为启用 Provider；缺少 `DASHSCOPE_API_KEY` 和 `DOUBAO_API_KEY` 被报告为警告，没有泄露密钥内容。

### 4.4 Web 端到端验证

使用测试环境路径启动真实 Uvicorn 进程：

```text
NOVAAGENT_DATA_DIR=/private/tmp/novaagent-data \
NOVAAGENT_LOG_DIR=/private/tmp/novaagent-logs \
NOVAAGENT_WORKSPACE_DIR=/private/tmp/novaagent-workspace \
uv run novaagent serve --environment test
```

启动后访问：

```text
curl -sS http://127.0.0.1:8765/health/live
curl -sS http://127.0.0.1:8765/health/ready
curl -sS http://127.0.0.1:8765/api/v1/diagnostics
```

结果：

- `/health/live` 返回 `status: ok`。
- `/health/ready` 返回 `status: ready`。
- `/api/v1/diagnostics` 返回 Python、Web、路径和 Provider 状态，未返回 API 密钥或 Token。
- 发送停止信号后进程正常退出。

## 5. 设计与实现偏差

| 项目 | 设计 | 实际实现 | 影响 |
| --- | --- | --- | --- |
| Provider 目录 | 设计示例使用 `infrastructure/providers/` | 阶段 01保留 Provider 占位包，实际适配器未创建 | 无影响，真实适配器在阶段 03/14 创建 |
| Web 前端 | 阶段 01只要求占位页 | 当前根路径返回 JSON 占位信息，尚未创建 HTML 页面 | 符合“不实现完整控制台”的阶段边界 |
| 测试客户端 | 设计要求 Web 集成测试 | 使用 FastAPI TestClient 验证路由 | 当前有上游弃用警告，后续需处理 |
| CI | 总体路线要求 CI 和本地验证 | 已有 `scripts/verify.sh` 和 GitHub Actions workflow | 已满足；首次推送后确认 GitHub Actions 运行结果 |
| 覆盖率 | 核心配置逻辑目标不低于 90% | 配置加载器 98%、配置模型 97%、路径模块 100% | 已满足；全项目总覆盖率为 85% |

以上偏差没有扩大产品范围，也没有引入额外模型或用户通道。

## 6. 安全与范围确认

- 没有实现真实千问或豆包请求，不会在阶段 01 意外消耗模型配额。
- 默认 Web 监听地址为 `127.0.0.1`。
- 非回环 Web 配置必须使用 Token 认证。
- Provider 配置只允许千问和豆包。
- API 密钥只从环境变量读取，不写入 TOML、日志、诊断或测试输出。
- CLI 不提供终端聊天。
- 未实现第三方即时通信渠道、桌面客户端、Shell、文件工具、浏览器和 MCP。

## 7. 待完成事项

正式把阶段 01 标记为“已验收”前，需要完成：

1. 已完成配置加载器、配置模型和路径边界的失败路径测试，核心模块覆盖率达到 90% 以上。
2. 已添加 CI workflow，执行锁定依赖安装、Pytest 与覆盖率、Ruff lint、Ruff 格式检查、Mypy 和 `doctor`。
3. 决定如何处理 Starlette/TestClient 的弃用警告，并更新依赖或测试客户端实现。
4. 运行一次干净环境演示并保存完整命令输出，作为最终完成报告附件或补充记录。
5. 由项目负责人确认本报告中的设计偏差和遗留项后，更新阶段状态。

## 8. 下一阶段

阶段 01 完成正式验收后，进入阶段 02：核心消息与事件协议。阶段 02 的设计应在本阶段已建立的配置、Web 生命周期、错误、日志和依赖边界之上，定义：

- `Message`、`ContentBlock` 和角色语义。
- `AgentEvent` 的类型、顺序和终止语义。
- Model、Tool、Session Store 和事件接收器的最小 Port。
- Web JSON 序列化和版本字段。
- 假模型和内存事件接收器的契约测试。

阶段 02 不应重新设计阶段 01 已确认的 Provider 白名单、Web 唯一入口或管理 CLI 边界。
