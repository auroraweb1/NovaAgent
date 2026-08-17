# 阶段 02 完成报告：核心消息与事件协议

> 状态：已验收
>
> 创建日期：2026-08-17
>
> 验收日期：2026-08-17
>
> 设计文档：[design.md](./design.md)
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 报告目的

本文记录阶段 02 的实际实现、自动化测试、最小协议演示、覆盖率、设计差异和验收决策。阶段 02 的设计、编码和自动化质量门禁已经完成，并已由项目负责人确认通过验收。

本报告不代表真实模型、聊天 API、流式 Web 页面、会话持久化或工具执行已经完成。阶段 02 只建立这些后续能力共同依赖的供应商无关核心协议；千问接入和 Web 单轮聊天仍属于阶段 03。

后续范围变更：项目负责人于 2026-08-17 确认 NovaAgent 只使用千问，不再接入豆包，也不建设模型多模态任务。六类 `ContentBlock` 的历史实现和测试继续保留，但图片、音频和文件引用块不再安排模型多模态处理；本报告中的双 Provider 诊断结果仅属于阶段 02 当时的回归证据。

## 2. 阶段结论

阶段 02 的最小协议闭环已经实现并通过自动化验证：

```text
统一 user Message
  → Scripted/Fake Model
  → 类型化 ModelOutput
  → 连续 AgentEvent 序列
  → In-memory Event Sink
  → 最终 assistant Message
  → JSON 序列化往返
```

关键结果如下：

1. `Message`、六类 `ContentBlock`、角色语义和不可变 JSON 值已经实现。
2. `AgentEvent`、十二类事件 payload、Token 使用量和增量顺序状态机已经实现。
3. Model、Event Sink、Tool 和 Session Store 的最小异步 Port 已经实现，Domain 不依赖 Web 或 Provider SDK。
4. Web 边界使用 Pydantic Schema 校验，再显式转换标准库 Domain 对象；协议主版本为 `"1"`。
5. 空白输入、思考摘要、终止错误、版本兼容和 Fake 仅位于测试目录等已确认决策均已落实。
6. 86 个自动化测试全部通过，总覆盖率 95%；阶段 02 核心模块覆盖率为 96%～100%。
7. Ruff、格式检查、Mypy 和 `novaagent doctor --environment test` 全部通过，阶段 01 能力没有回归。
8. 项目负责人确认实现范围、协议形状、设计差异和最小演示证据均可接受，阶段结论为“通过”。

## 3. 已交付内容

### 3.1 Message 与 ContentBlock（PRO-01、PRO-02）

实现位置：

- [`domain/messages.py`](../../../src/novaagent/domain/messages.py)
- [`domain/errors.py`](../../../src/novaagent/domain/errors.py)

已实现：

- `MessageRole`：`system`、`user`、`assistant`、`tool`。
- `TextBlock`、`ImageRefBlock`、`AudioRefBlock`、`FileRefBlock`、`ToolCallBlock` 和 `ToolResultBlock`。
- 冻结 dataclass、元组内容和递归防御性 JSON 冻结。
- ID、UTC 时间、MIME、大小、SHA-256、工具状态和角色/内容组合校验。
- 空字符串 TextBlock 拒绝，只有空白 TextBlock 的最终 Message 拒绝。
- Application 入口空白输入拒绝，稳定错误码为 `message_empty`，合法原文不裁剪。

### 3.2 AgentEvent 与状态机（PRO-03、PRO-04）

实现位置：[`domain/events.py`](../../../src/novaagent/domain/events.py)

已实现事件：

- `run_started`
- `message_started`
- `text_delta`
- `reasoning_summary_delta`
- `tool_call`
- `tool_result`
- `artifact`
- `error`
- `message_completed`
- `run_completed`
- `run_failed`
- `run_cancelled`

状态机直接保证：

- 首事件必须是 `run_started`，sequence 从 0 连续增长。
- 同一序列只能使用一个 `run_id`，`event_id` 不得重复。
- 文本增量、最终消息、工具调用和工具结果必须满足关联顺序。
- 存在文本增量时，其聚合文本必须等于最终 Message 文本。
- 每个 run 必须且只能有一个成功、失败或取消终止事件。
- 对外 `error` 必须立即跟随 `run_failed`，错误码必须一致。
- 终止事件后禁止继续发布事件。

### 3.3 核心 Port 与驱动流程（PRO-05～PRO-07）

实现位置：

- [`domain/ports.py`](../../../src/novaagent/domain/ports.py)
- [`application/protocol/driver.py`](../../../src/novaagent/application/protocol/driver.py)

已实现：

- `ModelPort.stream()` 的异步统一输出流。
- 文本、思考摘要、工具调用和 Token 使用量模型输出。
- `EventSinkPort.publish()` 异步事件发布。
- 工具定义与异步工具执行分离的 `ToolPort`。
- 异步 `SessionStorePort`，阶段 02 未加入乐观并发版本。
- 单次协议驱动流程，包括成功终止、脱敏失败终止和思考摘要上限。
- 每个 run 最多传输 4096 个思考摘要字符，超限提示只发布一次。
- Event Sink 自身失败不会被错误标记成模型失败。

测试替身只位于 [`tests/fakes/protocol.py`](../../../tests/fakes/protocol.py)，没有进入生产包或 Bootstrap：

- `ScriptedModel`
- `InMemoryEventSink`
- `InMemorySessionStore`

### 3.4 序列化与版本（PRO-08）

实现位置：[`interfaces/web/protocol.py`](../../../src/novaagent/interfaces/web/protocol.py)

已实现：

- 独立 Message 和 AgentEvent JSON 顶层 `protocol_version: "1"`。
- ContentBlock 的 `type` 判别联合和 AgentEvent 的显式 payload 转换。
- UTC RFC 3339 `Z` 时间、稳定小写枚举和 `snake_case` 字段。
- 空 `metadata` 固定输出 `{}`，值为 `None` 的非关键字段省略。
- 同主版本未知可选字段忽略；未知主版本、未知类型和缺少必填字段拒绝。
- Pydantic 只存在于 Web 接口边界，Domain 使用标准库类型。
- 全部内容块及事件 payload 的 JSON 语义往返。

## 4. 测试与验证证据

### 4.1 自动化测试与覆盖率

执行命令：

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run pytest --cov=novaagent --cov-report=term-missing
```

结果：`86 passed`，总覆盖率 `95%`。

阶段 02 核心模块覆盖率：

| 模块 | 覆盖率 |
| --- | --- |
| `application/protocol/driver.py` | 100% |
| `domain/events.py` | 100% |
| `domain/ports.py` | 100% |
| `domain/messages.py` | 97% |
| `interfaces/web/protocol.py` | 96% |

测试覆盖：

- 合法与非法 Message、ContentBlock、资源引用、工具调用和工具结果。
- 空字符串、纯空格、换行和制表符用户输入。
- JSON 参数和 metadata 的防御性复制、冻结和非法值拒绝。
- 成功、失败、取消、序号错误、关联错误、重复终止和终止后事件。
- `event_id`、`run_id`、`message_id` 和 `call_id` 关联规则。
- 有思考摘要、无思考摘要、摘要超限和单次截断提示。
- 全部 Message、ContentBlock 和 AgentEvent JSON 往返。
- 未知主版本、未知 type、缺少字段和非法 payload。
- Fake 对异步 Port 的静态类型和运行行为。
- Domain 禁止导入 FastAPI、Pydantic、HTTPX、HTTPX2 或 Provider SDK。
- 阶段 01 配置、Web、CLI 和诊断测试回归。

### 4.2 质量检查

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff check .
```

结果：`All checks passed!`

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff format --check .
```

结果：`50 files already formatted`。

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run mypy src tests
```

结果：`Success: no issues found in 43 source files`。

### 4.3 阶段 01 回归诊断

```text
NOVAAGENT_DATA_DIR=/private/tmp/novaagent-stage02-data \
NOVAAGENT_LOG_DIR=/private/tmp/novaagent-stage02-logs \
NOVAAGENT_WORKSPACE_DIR=/private/tmp/novaagent-stage02-workspace \
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache \
uv run novaagent doctor --environment test
```

结果：返回 `status: ok`；阶段 02 验收时千问和豆包是启用 Provider，缺少两家密钥只产生预期警告且未泄露密钥内容。当前产品已收敛为仅千问，遗留豆包诊断由 MOD-06 跟踪清理。

## 5. 设计与实现差异

| 项目 | 设计要求 | 实际结果 | 影响 |
| --- | --- | --- | --- |
| 阶段 01 占位 Message | 实现时替换 `Message(role, text)` | 已替换为正式 Message/ContentBlock；仓库中没有旧调用方 | 无兼容负担 |
| `DiagnosticEvent` | 与聊天 AgentEvent 保持分离 | 原工程诊断对象继续保留，未并入聊天状态机 | 保持阶段 01 诊断稳定 |
| `HealthPort` | 不并入模型或会话 Port | 继续独立保留 | 无回归 |
| Token 使用量 | ModelOutput 可表达使用量 | 使用 `TokenUsage` 和 `UsageModelOutput`，最终附加到 `run_completed` | 为阶段 03 Provider 适配提供稳定落点 |
| Fake 与 In-memory 实现 | 只放测试目录 | 全部位于 `tests/fakes/`，生产包不提供演示替身 | 符合设计 |
| Web 聊天入口 | 阶段 02 不创建 | 只增加 Web JSON Schema/转换模块，没有新增路由或页面 | 符合阶段边界 |

未发现需要改变已确认产品范围的设计偏差，也没有引入第三个 Provider、CLI 聊天或其他用户通道。

## 6. 安全与产品边界确认

- 未发起任何真实模型请求。
- 未读取、记录或持久化模型密钥。
- 思考摘要不写入 Message、Session Store、日志或下一轮上下文。
- 不展示或模拟原始思维链；只定义安全摘要事件。
- 模型异常转换为脱敏错误；测试确认原始异常文本不会进入事件。
- 资源 Block 只保存受控引用，不嵌入 Base64 或任意公网 URL。
- 没有实现工具执行、Shell、文件访问、网络访问或其他副作用。
- 没有增加聊天 API、聊天 CLI、桌面入口或第三方消息通道。
- 阶段 02 验收时 Provider 范围为千问和豆包；当前范围已收敛为仅千问，用户通道仍固定为 Web 控制台。

## 7. 验收决策

项目负责人于 2026-08-17 确认：

1. 本报告记录的实现范围、协议形状和设计差异可以接受。
2. 测试驱动的 Fake Model → AgentEvent → Event Sink → 最终 Message → JSON 往返足以作为阶段 02 最小演示证据。
3. 阶段 02 不需要真实模型或 Web 聊天入口演示；这些能力按路线保留在阶段 03。
4. 阶段 02 和 PRO-01～PRO-08 可以更新为“已完成/已验收”，阶段 03 可以进入设计。

## 8. 阶段结论

阶段结论：**通过**。

阶段 02 已具备稳定、不可变、可序列化并可由假实现确定性验证的核心消息与事件协议。项目负责人已经确认最小演示证据和设计差异，阶段 02 正式完成验收，允许阶段 03 进入设计。
