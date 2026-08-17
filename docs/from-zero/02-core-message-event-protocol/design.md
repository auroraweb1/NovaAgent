# 阶段 02：核心消息与事件协议

> 状态：已确认；已实现；已验收
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-17
>
> 前置阶段：阶段 01“产品边界与工程地基”已验收
>
> 适用项目：NovaAgent
>
> 项目根目录：`/Users/jiaojie/NovaAgent`
>
> 编码许可：已开放；项目负责人于 2026-08-17 确认开始阶段 02 实现

## 1. 文档目的

本文是 NovaAgent 阶段 02“核心消息与事件协议”的已确认设计。它负责定义 Web、应用服务、模型适配器、工具和会话存储之间共同使用的内部语言，使后续能力建立在稳定、可测试且与供应商无关的协议上。

项目负责人已完成整体评审并开放编码许可。第 19、20 节中的产品和技术决策已经确认，阶段 02 实现、自动化测试和验收已经完成；实际结果、验证证据和验收决策记录在 `completion-report.md`。

本文不改变阶段 01 已验收的产品边界：

- 千问和豆包仍是唯一允许的模型 Provider。
- Web 控制台仍是唯一用户聊天入口。
- CLI 仍只承担诊断和服务管理，不增加聊天命令。
- 阶段 02 不发起真实模型请求，不实现聊天页面，也不实现工具执行。

## 2. 阶段目标

阶段 02 结束时，NovaAgent 应当具备一套可以独立于 FastAPI、HTTPX、千问和豆包 SDK 运行的核心协议，并能够使用假实现完成以下确定性流程：

```text
原始测试输入
  → 转换为统一 Message
  → Fake Model Port 接收消息
  → 产生确定顺序的模型输出
  → 应用层转换为 AgentEvent
  → In-memory Event Sink 按顺序接收
  → 聚合得到完整回复
  → JSON 序列化后仍保持相同语义
```

本阶段交付目标如下：

- PRO-01：定义不可变的统一 `Message` 和角色语义。
- PRO-02：定义带显式类型判别字段的 `ContentBlock` 联合类型。
- PRO-03：定义统一 `AgentEvent` 信封和事件类型。
- PRO-04：定义事件顺序、关联和终止状态机。
- PRO-05：定义不泄漏供应商对象的最小 `ModelPort`。
- PRO-06：定义工具描述与工具执行分离的最小 `ToolPort`。
- PRO-07：定义会话消息读写的最小 `SessionStorePort`。
- PRO-08：定义协议版本、JSON 序列化和兼容规则。
- 提供只用于测试的 Fake Model、In-memory Event Sink 和 In-memory Session Store。
- 建立领域不依赖 Web/Provider SDK 的依赖边界测试。
- 建立协议不变量、序列化往返和事件顺序契约测试。

## 3. 阶段非目标

本阶段不实现以下内容：

- 不接入千问、豆包或任何真实模型 API。
- 不增加其他模型 Provider、自定义模型端点或动态 Provider 注册。
- 不实现 `/chat`、`/sessions`、SSE、WebSocket 或聊天页面。
- 不实现 Agent 决策循环、工具注册表或任何真实工具。
- 不实现 SQLite、会话恢复、长期记忆或知识库。
- 不解析图片、音频和文件内容，不调用多模态模型。
- 不实现 token 预算、上下文裁剪、重试、限流或模型计费。
- 不建立第二套终端或第三方消息通道协议。
- 不承诺保存或展示模型的原始思维链。
- 不为了未来能力创建没有本阶段测试和调用方的抽象层。

阶段 02 可以定义后续能力需要的协议形状，但对应运行能力必须留在后续阶段实现。

## 4. 设计约束

### 4.1 依赖方向

阶段 01 已确认的依赖方向继续生效：

```text
interfaces / bootstrap
          ↓
application
          ↓
domain
          ↑
infrastructure implements domain ports
```

核心协议必须满足：

1. `domain` 只使用 Python 标准库类型，不导入 FastAPI、Pydantic、HTTPX、HTTPX2 或供应商 SDK。
2. Web JSON Schema 和领域对象是两个边界；Web 层使用 Pydantic Schema 校验 HTTP 输入输出，并通过显式转换函数连接标准库领域对象，不把 Pydantic 模型当作领域对象传播。
3. Provider Adapter 只能返回统一模型输出，不能把 DashScope 或豆包响应对象传入应用层。
4. Session Store 保存和返回统一 `Message`，不能要求调用方了解数据库行或 JSON 文本。
5. Tool Port 使用统一定义、调用和结果对象，不能让模型请求参数直接控制运行时资源。

### 4.2 不可变性

拟定所有协议值对象使用冻结数据结构：

- 领域对象创建后不能原地修改。
- `Message.content` 使用元组而不是可变列表。
- JSON 对象参数进入领域前需要复制和校验，不能保留外部可变字典引用。
- 消息追加、事件推进和会话更新通过创建新值表达。

不可变性用于降低流式事件、并发会话和后续持久化中的共享状态风险。

### 4.3 显式类型而非隐式字典

不继承 CowAgent 中通过通用字典、动态属性或散落字符串传递消息类型的方式。每个协议对象必须具备：

- 明确的类型名称。
- 明确的必填和可选字段。
- 可验证的不变量。
- 稳定的序列化判别字段。
- 对未知类型和非法组合的明确错误。

`metadata` 只能承载非关键扩展信息，不能用来绕过正式字段或改变核心状态机。序列化时固定输出空对象 `{}`，为消费者维持单一稳定形态。

## 5. 基础类型

### 5.1 标识符

拟定在领域协议中将标识符表示为经过校验的非空字符串，而不把 UUID 实现细节写入 Port。创建标识符的应用层可以使用 UUID，但领域消费者只依赖其不透明、稳定和在所属范围内唯一的语义。

阶段 02 涉及以下标识符：

| 字段 | 作用域 | 语义 |
| --- | --- | --- |
| `message_id` | 会话 | 唯一标识一条最终消息 |
| `run_id` | 一次执行 | 关联同一次请求产生的全部事件 |
| `event_id` | 全局或事件存储 | 唯一标识一个事件 |
| `session_id` | 用户会话 | 关联消息历史；阶段 02 只使用测试值 |
| `call_id` | 一次 run | 关联工具调用和对应结果 |
| `artifact_id` | 一次 run 或会话 | 关联文件或其他产物描述 |

空字符串、只包含空白的字符串和在同一集合中重复的标识符必须被拒绝。

### 5.2 时间

领域对象中的绝对时间拟定使用带时区的 UTC `datetime`。JSON 边界使用 RFC 3339 字符串并统一输出 `Z` 后缀。

事件顺序不依赖时间戳判断，而以 `run_id + sequence` 为准。时间只用于观察、存储和跨进程诊断，避免系统时钟回拨破坏顺序。

### 5.3 JSON 值

协议允许的扩展值和工具参数必须限制为标准 JSON 值：

```text
null | boolean | number | string | array | object
```

不允许把文件句柄、异常对象、SDK 响应、Python 类实例或任意可调用对象放入协议字段。

## 6. Message 设计（PRO-01）

### 6.1 拟定结构

`Message` 表示会话中已经形成稳定语义的一条消息，而不是流式传输中的单个分片。

拟定字段如下：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `message_id` | 非空字符串 | 是 | 消息标识符 |
| `role` | `MessageRole` | 是 | `system`、`user`、`assistant` 或 `tool` |
| `content` | `tuple[ContentBlock, ...]` | 是 | 至少包含一个内容块 |
| `created_at` | UTC `datetime` | 是 | 消息形成时间 |
| `name` | 非空字符串或 `None` | 否 | 可选的参与者或工具名称，不承担身份认证 |
| `metadata` | 只读 JSON object | 否 | 非关键扩展信息，默认空对象 |

### 6.2 角色语义

| 角色 | 产生者 | 允许的主要内容 | 约束 |
| --- | --- | --- | --- |
| `system` | 应用装配或 Prompt 组装 | 文本 | 不直接来自 Web 用户输入 |
| `user` | Web 输入边界 | 文本、资源引用 | 阶段 02 只测试文本；后续阶段启用资源处理 |
| `assistant` | 模型或 Agent | 文本、工具调用 | 不保存供应商原始响应对象 |
| `tool` | 工具执行层 | 工具结果 | 必须能够通过 `call_id` 找到对应调用 |

角色不是权限系统。应用层仍需根据用户、会话和工具策略判断是否允许操作。

### 6.3 Message 不变量

- `content` 不能为空。
- 最终 Message 必须至少包含一个有实际语义的内容块；只有空白 TextBlock 的消息不合法。
- `content` 中不能出现未知 Block 类型。
- `tool` 角色至少包含一个 `ToolResultBlock`。
- `ToolResultBlock.call_id` 必须是非空字符串。
- `assistant` 的工具调用必须使用 `ToolCallBlock`，不能把调用参数伪装进文本或 metadata。
- 最终 `Message` 不包含 `TextDelta`；流式分片只存在于事件中。
- metadata 不能覆盖 `message_id`、`role`、`content` 或 `created_at`。

### 6.4 空白用户输入

空白输入在 Web/Application 边界拒绝，不进入领域执行流程。确认规则如下：

- `""`、纯空格、纯换行和纯制表符均视为空白输入。
- Web 控制台提示“请输入内容后再发送”。
- Web API 在阶段 03 实现时返回 HTTP `422` 和稳定错误码 `message_empty`，字段路径为 `message`。
- 空白输入不创建 `Message`、`run_id` 或 `AgentEvent`，不写入会话，也不调用模型。
- 输入校验可以用 `strip()` 判断是否为空，但合法输入进入 TextBlock 时保留原始文本，不自动删除有意义的首尾空格或换行。
- 包含非文本资源的用户消息是否允许没有文本，由对应文件和多模态阶段另行确认；阶段 02 的最小输入只接受有实际内容的文本。

## 7. ContentBlock 设计（PRO-02）

### 7.1 判别联合

所有内容块使用稳定的 `type` 判别字段。拟定类型如下：

| 领域类型 | JSON `type` | 阶段 02 行为 | 后续阶段 |
| --- | --- | --- | --- |
| `TextBlock` | `text` | 完整实现和测试 | 全阶段复用 |
| `ImageRefBlock` | `image_ref` | 定义结构并验证引用，不读取内容 | 阶段 14 启用模型处理 |
| `AudioRefBlock` | `audio_ref` | 定义结构并验证引用，不读取内容 | 阶段 14 确认能力 |
| `FileRefBlock` | `file_ref` | 定义结构并验证引用，不读取内容 | 阶段 07/14 启用上传和预览 |
| `ToolCallBlock` | `tool_call` | 定义结构和契约测试，不执行 | 阶段 05 执行 |
| `ToolResultBlock` | `tool_result` | 定义结构和契约测试，不执行 | 阶段 05 回填 |

资源 Block 只保存受控引用和描述信息，不直接在 JSON 中嵌入无限大小的 Base64 数据。

### 7.2 TextBlock

拟定字段：

```text
type = "text"
text: str
```

`TextBlock.text` 不能是空字符串，协议层保留原始文本，不自动裁剪首尾空白。单个 TextBlock 可以包含格式所需的空白，但最终 Message 不能只由空白 TextBlock 构成；用户入口同时遵守第 6.4 节的空白输入拒绝规则。

### 7.3 资源引用 Block

`ImageRefBlock`、`AudioRefBlock` 和 `FileRefBlock` 共享拟定的资源引用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `resource_id` | 非空字符串 | NovaAgent 内部资源标识 |
| `media_type` | 非空字符串 | MIME 类型 |
| `name` | 字符串或 `None` | 安全展示名称，不作为文件系统路径 |
| `size_bytes` | 非负整数或 `None` | 已知时记录大小 |
| `sha256` | 十六进制字符串或 `None` | 已知时用于完整性检查 |

阶段 02 不定义任意公网 URL Block。后续文件阶段必须在认证、SSRF、路径和生命周期规则确定后，把外部输入转换为受控 `resource_id`。

### 7.4 ToolCallBlock

拟定字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `call_id` | 非空字符串 | 本次 run 内唯一 |
| `tool_name` | 非空字符串 | 逻辑工具名称 |
| `arguments` | JSON object | 已完成解析但尚未执行的参数 |

模型输出的原始参数字符串不直接成为 `ToolCallBlock`。Provider Adapter 或应用边界必须先完成 JSON 解析；解析失败产生标准错误事件。

### 7.5 ToolResultBlock

拟定字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `call_id` | 非空字符串 | 对应 `ToolCallBlock.call_id` |
| `status` | `success` 或 `error` | 执行结果分类 |
| `content` | `tuple[ContentBlock, ...]` | 工具返回的安全内容 |
| `error_code` | 字符串或 `None` | 失败时的稳定错误码 |

工具异常、堆栈和运行时对象不得直接放入结果。用户可见信息和内部日志信息需要分离。

## 8. AgentEvent 设计（PRO-03）

### 8.1 统一事件信封

领域中的每个事件拟定包含以下公共字段；独立序列化时，由接口或存储边界在 JSON 顶层额外加入 `protocol_version`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | 非空字符串 | 事件唯一标识 |
| `run_id` | 非空字符串 | 所属执行 |
| `sequence` | 非负整数 | 同一 run 内严格递增 |
| `type` | 事件判别字符串 | 决定 payload 结构 |
| `occurred_at` | UTC `datetime` | 观察时间，不决定顺序 |
| `payload` | 类型化 payload | 只包含该事件需要的字段 |

领域实现应使用带类型的事件类或判别联合，而不是把所有事件都实现为 `dict[str, Any]`。

### 8.2 拟定事件类型

| 事件类型 | 作用 | 阶段 02 是否产生 |
| --- | --- | --- |
| `run_started` | 一次执行开始 | 是 |
| `message_started` | assistant 消息开始形成 | 是 |
| `text_delta` | 增量文本 | 是 |
| `reasoning_summary_delta` | 供应商明确提供且允许展示的思考摘要增量 | 是；Fake Model 可选产生 |
| `tool_call` | 完整、已解析的工具调用请求 | 契约定义，不执行 |
| `tool_result` | 工具执行结果 | 契约定义，不执行 |
| `artifact` | 文件或其他产物引用 | 契约定义，不创建真实文件 |
| `error` | 当前 run 无法继续时的脱敏标准错误 | 是，产生后必须以 `run_failed` 终止 |
| `message_completed` | 最终 assistant Message 已形成 | 是 |
| `run_completed` | run 成功终止，可携带最终模型 Token 使用量 | 是 |
| `run_failed` | run 失败终止 | 是 |
| `run_cancelled` | run 被取消终止 | 契约定义，阶段 04 实现取消 |

### 8.3 思考摘要边界

NovaAgent 支持可选的 `reasoning_summary_delta`，产品展示名称使用“思考摘要”或“处理思路”，不使用“完整推理过程”。该事件只表达供应商明确区分、允许面向用户展示的摘要，不承诺暴露模型内部思维链。

确认规则如下：

- 不把隐藏推理提示、内部安全策略、原始思维链、密钥、文件保护规则或其他敏感信息写入事件。
- Provider 只有在提供明确、独立且可安全展示的摘要字段时，适配器才能映射该事件。
- Provider 不支持安全摘要时完全不产生该事件，不输出空事件或空 UI 卡片，也不引入第三个 Provider 补齐能力。
- 不从普通最终回答中猜测、生成或伪造推理摘要。
- Provider 只返回 `<think>...</think>` 等原始推理内容时，不默认直接展示；必须在该 Provider 阶段确认可靠语义，否则丢弃推理部分，只保留最终回答。
- Web 必须能够在完全没有思考摘要事件时正常工作；未来界面默认使用可折叠卡片展示。
- 每个 run 最多向用户展示 4096 个 Unicode 字符的摘要。超过上限后停止发送，并只产生一次“思考摘要过长，后续内容已省略”提示。
- 摘要默认不写入会话历史或数据库，不进入下一轮模型上下文，也不写入日志。页面刷新或会话恢复只保证恢复最终回答。
- 摘要传输或展示失败不能导致最终回答失败。

合法事件流可以完全没有 `reasoning_summary_delta`。阶段 02 的 Fake Model 应同时覆盖“有摘要”和“无摘要”两种契约，但不模拟或生成原始思维链。

### 8.4 错误事件

确认 `error` payload 包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | 非空字符串 | 稳定机器错误码 |
| `message` | 非空字符串 | 已脱敏的用户可读信息 |
| `retryable` | 布尔值 | 当前 run 失败后，是否适合建议用户重新发起请求 |
| `field` | 字符串或 `None` | 输入或配置字段路径 |

对外发布的 `error` 一律表示当前 run 已无法继续，其后必须紧跟 `run_failed`。Provider 或工具的内部自动重试过程不发布 `error`；只有重试耗尽或确认无法继续时才发布。`retryable=true` 只表示 Web 可以提供“重试”操作，不表示当前 run 会恢复执行。未来若需要非终止提示，应新增语义独立的 `warning` 事件，不能复用 `error`。

## 9. 事件顺序与终止语义（PRO-04）

### 9.1 基本规则

同一 `run_id` 的事件必须满足：

1. 第一个事件必须是 `run_started`，`sequence` 为 `0`。
2. 后续事件的 `sequence` 必须严格连续递增，不能重复、回退或跳号。
3. `message_started` 必须早于属于该消息的 `text_delta` 和 `message_completed`。
4. `message_completed` 最多出现一次，并携带聚合后的最终 `Message`。
5. 终止事件只能是 `run_completed`、`run_failed` 或 `run_cancelled` 之一。
6. 每个 run 必须且只能有一个终止事件。
7. 终止事件后不得再产生任何事件。
8. 对外 `error` 的下一个事件必须是 `run_failed`；该 run 不能继续输出或以 completed 结束。
9. `run_completed` 需要成功的最终结果，不能缺少最终 Message。
10. `tool_result.call_id` 必须对应同一 run 中先前出现的 `tool_call.call_id`。
11. 未知事件类型必须在解析边界被拒绝，不能静默当作文本处理。

### 9.2 成功序列示例

```text
0 run_started
1 message_started
2 text_delta("你")
3 text_delta("好")
4 message_completed(Message("你好"))
5 run_completed
```

### 9.3 失败序列示例

```text
0 run_started
1 message_started
2 text_delta("部分内容")
3 error(code="model_unavailable", retryable=true)
4 run_failed
```

失败序列中的部分文本是否进入会话历史由阶段 04 的会话设计决定；阶段 02 只保证事件事实不会被伪装成成功的最终消息。

### 9.4 顺序验证器

拟定实现一个纯领域状态机验证事件序列。验证器：

- 不执行 I/O。
- 不依赖 Web、模型或数据库。
- 可以逐事件验证，也可以验证完整事件集合。
- 对首事件错误、序号错误、关联错误、重复终止和终止后事件返回稳定协议错误。

## 10. 核心 Port（PRO-05 ～ PRO-07）

### 10.1 ModelPort

拟定 `ModelPort` 是异步协议，因为真实 Provider、流式输出和取消都依赖异步 I/O。它接收统一请求并产生供应商无关的模型输出，不直接产生 Web JSON。

概念结构：

```text
ModelRequest
  messages: tuple[Message, ...]
  tools: tuple[ToolDefinition, ...]
  options: ModelOptions

async ModelPort.stream(request) -> AsyncIterator[ModelOutput]
```

`ModelOutput` 只表达模型本身可产生的文本增量、安全思考摘要、工具调用和使用量信息。应用层负责把它包装为带 `run_id`、顺序和终止语义的 `AgentEvent`。

约束：

- Port 不暴露 URL、HTTP Header、SDK Request/Response 或供应商异常。
- 阶段 02 的 Fake Model 根据固定脚本产生输出，不访问网络。
- 单轮非流式调用可以消费完整流并聚合，避免维护两套响应协议。
- 真实千问适配器留到阶段 03，豆包适配器留到阶段 14。

### 10.2 EventSinkPort

事件接收器确认使用异步发布接口：

```text
async EventSinkPort.publish(event: AgentEvent) -> None
```

阶段 02 提供 In-memory Event Sink，用于：

- 保存收到的事件顺序。
- 运行顺序验证器。
- 聚合文本结果。
- 支持契约测试断言。

Web SSE/WebSocket、日志和持久事件存储都是未来可能的适配器，本阶段不实现。

### 10.3 ToolPort

阶段 02 只定义最小工具边界：

```text
ToolPort.definition() -> ToolDefinition
async ToolPort.execute(call: ToolCall, context: ToolExecutionContext) -> ToolResult
```

拟定 `ToolDefinition` 包含稳定名称、说明和 JSON Schema 参数定义；`ToolExecutionContext` 只包含执行所需的显式上下文标识，不直接暴露全局配置或应用容器。

本阶段不实现工具注册表和真实工具。测试可以定义无副作用假工具验证类型契约，但最小演示不执行工具。

### 10.4 SessionStorePort

确认最小会话存储协议使用异步 I/O：

```text
async get_messages(session_id) -> tuple[Message, ...]
async append_messages(session_id, messages) -> None
```

约束：

- 返回顺序必须稳定，按会话消息顺序排列。
- 追加一组消息必须具有原子语义；失败时不能只写入一部分。
- Store 不生成 Prompt，也不裁剪上下文。
- 阶段 02 不在 Port 中加入乐观并发版本，只提供位于测试目录的 In-memory 实现。
- 阶段 04 在真实多会话和并发规则明确后决定是否加入乐观并发版本，阶段 10 实现持久化。

## 11. 序列化与版本（PRO-08）

### 11.1 JSON 规则

确认 JSON 使用以下规则：

- 字段名统一为 `snake_case`。
- 独立序列化的 `Message` 和 `AgentEvent` 顶层包含 `protocol_version`，初始版本为字符串 `"1"`；嵌套 ContentBlock 不重复携带版本。
- Domain 值对象不把 `protocol_version` 作为业务字段；接口或存储序列化边界负责添加、读取和校验版本。
- Block 和 Event 使用 `type` 作为判别字段。
- 时间使用 UTC RFC 3339 字符串。
- 枚举值使用稳定小写字符串。
- 不输出值为 `None` 的非关键可选字段，减少协议噪声。
- `metadata` 即使为空也固定输出 `{}`，避免消费者同时处理缺失和空对象两种形态。
- 输出必须可由标准 `json` 编码，不依赖 Python 专用标签。

Web JSON 边界确认使用接口层 Pydantic Schema 完成类型校验，再通过显式转换函数创建或序列化标准库领域对象。Pydantic Schema 不进入 Domain，也不能作为 Session Store 或 Model Port 的参数类型。

### 11.2 兼容规则

确认兼容策略：

1. 同一主版本内可以增加可选字段。
2. 读取已知类型时忽略未知可选字段，以支持新生产者向旧消费者渐进扩展。
3. 缺少必填字段必须失败。
4. 未知 `protocol_version` 主版本必须失败。
5. 未知 Block 或 Event `type` 必须失败，避免错误解释语义。
6. 删除字段、改变字段类型或改变现有枚举语义需要新主版本。
7. 旧 CowAgent 格式只能在显式导入或接口边界转换，不能成为领域联合类型的一部分。

### 11.3 JSON 示例

拟定 Message JSON：

```json
{
  "protocol_version": "1",
  "message_id": "msg-001",
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": "你好"
    }
  ],
  "created_at": "2026-08-17T10:00:00Z",
  "metadata": {}
}
```

拟定文本事件 JSON：

```json
{
  "protocol_version": "1",
  "event_id": "evt-002",
  "run_id": "run-001",
  "sequence": 2,
  "type": "text_delta",
  "occurred_at": "2026-08-17T10:00:01Z",
  "payload": {
    "message_id": "msg-002",
    "delta": "你好"
  }
}
```

确认思考摘要事件 JSON：

```json
{
  "protocol_version": "1",
  "event_id": "evt-001",
  "run_id": "run-001",
  "sequence": 1,
  "type": "reasoning_summary_delta",
  "occurred_at": "2026-08-17T10:00:00Z",
  "payload": {
    "delta": "我会先确认输入条件，再比较可用方案。"
  }
}
```

## 12. 错误模型

阶段 02 确认在现有 `NovaAgentError` 体系下增加稳定协议错误，而不是抛出裸 `ValueError` 给接口层：

| 错误码 | 使用场景 |
| --- | --- |
| `protocol_invalid` | 缺少字段、非法枚举或对象不变量失败 |
| `protocol_version_unsupported` | 不支持的协议主版本 |
| `content_type_unsupported` | 未知或当前阶段不支持的内容类型 |
| `event_sequence_invalid` | 事件顺序、序号或终止语义错误 |
| `message_role_invalid` | 角色和 ContentBlock 组合非法 |
| `tool_call_invalid` | 工具调用参数或 call_id 非法 |
| `message_empty` | Web/Application 边界收到空白用户输入；不创建 Message 或 run |

错误信息必须包含安全的字段路径和稳定错误码，不回显可能包含密钥、完整文件内容或供应商原始响应的值。

## 13. 模块落点

实际实现落在以下最小文件中：

```text
src/novaagent/
├── domain/
│   ├── messages.py          # Message、ContentBlock 和相关值对象
│   ├── events.py            # AgentEvent 和顺序验证器
│   ├── ports.py             # Model/EventSink/Tool/SessionStore Port
│   └── errors.py            # 稳定协议错误
├── application/
│   └── protocol/
│       └── driver.py        # 假模型到事件接收器的最小应用流程
└── interfaces/
    └── web/
        └── protocol.py      # 领域对象和 JSON 之间的边界转换

tests/
├── fakes/
│   └── protocol.py
├── unit/
│   ├── test_messages.py
│   └── test_events.py
├── contract/
│   ├── test_protocol_serialization.py
│   └── test_protocol_ports.py
└── integration/
    └── test_protocol_driver.py
```

Fake Model、In-memory Event Sink 和 In-memory Session Store 确认只放在 `tests/fakes/` 或等价测试辅助目录，不提供可安装的生产或开发模块，不接入生产 Bootstrap。需要展示最小流程时直接运行集成测试，避免测试替身演变成第二套运行实现。

阶段 01 已存在的最小 `Message`、`DiagnosticEvent` 和 `HealthPort` 占位结构需要在实现时逐项评估：

- `Message(role, text)` 将由正式 Message/ContentBlock 协议替代，但需保持变更集中且有迁移测试。
- `DiagnosticEvent` 是工程诊断对象，不自动等同于 `AgentEvent`；如果继续保留，应明确它不属于聊天事件流。
- `HealthPort` 继续服务健康检查，不需要并入模型或会话 Port。

## 14. 测试设计

### 14.1 Message 和 ContentBlock 单元测试

- 所有合法角色和 Block 组合。
- 空 ID、空 content 和未知角色拒绝。
- 空白用户输入在入口被拒绝，不产生 Message、run 或事件。
- ToolCall/ToolResult 的 call_id 校验。
- 资源大小、MIME 类型和哈希格式校验。
- 冻结对象不能原地修改。
- 外部可变参数不能在对象创建后改变领域值。

### 14.2 AgentEvent 和顺序测试

- 成功文本事件序列。
- 失败和取消终止序列。
- 首事件不是 `run_started`。
- sequence 重复、回退和跳号。
- 缺少终止事件、重复终止事件和终止后事件。
- text delta 早于 message started。
- tool result 没有对应 tool call。
- `error` 后没有紧跟 `run_failed`。
- `error` 后错误地产生文本、工具事件或 `run_completed`。

### 14.3 序列化契约测试

- 每种 Message、Block 和 Event 的 JSON 往返。
- 固定示例快照，字段顺序不作为语义要求。
- 同版本未知可选字段可以读取。
- 未知主版本、未知 type 和缺少必填字段拒绝。
- 时间、枚举、JSON 参数和 Unicode 文本稳定编码。
- 序列化结果不包含 Python 类路径或供应商对象。

### 14.4 Port 契约测试

- Fake Model 只接收统一 `ModelRequest`，并覆盖有摘要和无摘要两种输出。
- In-memory Event Sink 保持事件顺序。
- In-memory Session Store 保持消息顺序和批量追加原子性，不提前引入乐观并发版本。
- 假 Tool Port 的定义与结果符合统一 Schema，不泄漏实现对象。
- Domain 模块不能导入 FastAPI、Pydantic、HTTPX、HTTPX2 或 Provider SDK；Web Pydantic Schema 只能存在于接口边界。

### 14.5 最小集成演示测试

测试驱动程序执行：

```text
user Message("你好")
  → Fake Model 输出 "你"、"好"
  → AgentEvent 序列
  → In-memory Event Sink
  → 最终 assistant Message("你好")
```

测试同时断言：

- 事件 sequence 从 0 连续增长。
- 只有一个终止事件。
- text delta 拼接结果等于最终 Message 文本。
- JSON 往返后事件语义不变。
- 没有网络请求、模型密钥或 Web 用户入口。

## 15. 质量和覆盖率目标

- 新增协议核心模块语句覆盖率不低于 90%。
- Message、Block 和事件顺序不变量必须覆盖全部失败分支。
- 序列化契约测试不得只依赖快照，必须同时断言语义字段。
- Ruff、格式检查、Mypy 和现有阶段 01 测试继续通过。
- GitHub Actions CI 必须通过。
- 测试输出不得包含模型密钥、Token、完整文件内容或供应商原始响应。

## 16. 实现顺序

阶段 02 已按以下顺序完成实现：

1. 在 `domain/messages.py` 实现基础类型、角色、Message 和 ContentBlock。
2. 在 `domain/events.py` 实现 AgentEvent 联合类型和顺序验证器。
3. 在 `domain/errors.py` 增加稳定协议错误。
4. 在 `domain/ports.py` 定义最小异步 Port，不加入阶段 04 才需要的并发版本字段。
5. 实现 JSON 边界转换和协议版本检查。
6. 在测试辅助代码中实现 Fake Model、In-memory Event Sink 和 Session Store。
7. 实现最小协议驱动流程，不连接 Web 聊天入口。
8. 补齐单元、契约和集成测试。
9. 运行完整 CI 等价验证并生成阶段 02 完成报告。

每一步必须保持现有健康检查、诊断和管理 CLI 可用。

## 17. 阶段验收标准

阶段 02 只有在以下条件全部满足后，才能进入阶段 03：

### 17.1 协议

- Message、ContentBlock 和 AgentEvent 的类型与不变量已实现。
- 文本、资源引用、工具调用和工具结果具有显式表达。
- 事件顺序验证器拒绝全部已定义非法序列。
- 一个 run 必须且只能以 completed、failed 或 cancelled 之一终止。

### 17.2 Port 和依赖边界

- Model、Event Sink、Tool 和 Session Store Port 不泄漏实现对象。
- Domain 不导入 Web、数据库、HTTP 或 Provider SDK。
- 假实现能够替换未来真实适配器完成确定性测试。

### 17.3 序列化

- 所有已支持协议对象能够稳定 JSON 往返。
- 未知可选字段、未知 type 和未知版本符合本文兼容规则。
- Web 边界可以消费事件 JSON，但阶段 02 不增加聊天 API。

### 17.4 验证

- 最小假模型事件流演示通过。
- 新增协议核心模块覆盖率不低于 90%。
- 完整 Pytest、Ruff、格式检查和 Mypy 通过。
- 阶段 01 的 CLI、健康检查和诊断能力没有回归。
- 完成报告记录设计偏差、测试证据和进入阶段 03 前的遗留项。

## 18. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 为未来所有模态过度设计 | 阶段 02 只完整实现文本路径；其他模态只定义最小引用协议 |
| Message metadata 退化成隐式参数袋 | 核心行为必须使用正式字段，metadata 限制为 JSON 且不得覆盖核心字段 |
| Provider 差异污染领域 | Provider Adapter 在边界转换，Port 不暴露 SDK 类型 |
| 事件类型过多且无法维护 | 事件必须对应明确消费者和顺序测试，未使用类型不提前实现行为 |
| 流式和非流式维护两套协议 | 非流式结果由统一输出流聚合得到 |
| 原始推理内容泄露 | 只允许 `reasoning_summary_delta`，默认可完全缺失；不保存、不记录、不进入下一轮上下文 |
| 工具参数携带不可序列化对象 | 参数严格限制为 JSON object |
| 协议版本过早复杂化 | 初始只使用主版本 `"1"`，不实现协商系统 |
| 阶段 02 偷跑聊天入口 | 不新增聊天 API 或 CLI；演示仅存在于自动化测试 |
| 空白输入污染会话 | 在 Web/Application 边界用 `message_empty` 拒绝，不创建 Message、run 或模型请求 |

## 19. 已确认设计问题

项目负责人已确认以下产品和技术问题，并已将结论落实到本文前述章节：

| 问题 | 已确认结论 |
| --- | --- |
| 空白 `TextBlock` | `TextBlock.text` 不能是空字符串；格式所需的空白可以保留，但最终 `Message` 不能只有空白 TextBlock；Web/Application 入口拒绝空白用户输入。 |
| `metadata` 序列化 | `metadata` 仅承载非关键扩展信息；即使为空也固定序列化为 `{}`，不允许覆盖正式字段。 |
| `protocol_version` 位置 | 独立序列化的 `Message` 和 `AgentEvent` 顶层都包含协议版本；Domain 对象不保存版本业务字段，Block 不重复携带版本。 |
| 思考摘要事件 | 使用 `reasoning_summary_delta`；仅允许 Provider 明确提供且安全可展示的摘要，最多 4096 个 Unicode 字符，默认不持久化、不写日志、不进入下一轮上下文；不展示或猜测原始思维链。 |
| `error` 终止语义 | 对外 `error` 一律表示当前 run 无法继续，下一事件必须是 `run_failed`；内部重试不发布 `error`，`retryable` 只表示是否建议用户重新发起。 |
| Session Store 并发 | 阶段 02 使用异步最小接口，不加入乐观并发版本；待阶段 04 根据真实多会话和并发规则决定。 |
| Fake 和 In-memory 实现 | 只放在 `tests/fakes/` 或等价测试辅助目录，不提供可安装的生产/开发模块，也不接入生产 Bootstrap。 |
| Web JSON 边界 | 接口层使用 Pydantic Schema 做 HTTP 校验，再通过显式转换函数连接标准库 Domain 对象；Pydantic 不进入 Domain、Port 或 Store。 |

## 20. 设计决策记录

以下决策均已确认并作为阶段 02 实现依据：

| 编号 | 拟定决策 | 状态 |
| --- | --- | --- |
| D02-01 | Domain 协议使用标准库冻结数据类和判别联合，不依赖 Pydantic | 已确认 |
| D02-02 | Message 使用内容块元组，不再保留顶层 `text` 作为核心存储 | 已确认 |
| D02-03 | 资源使用内部引用，不在协议 JSON 中嵌入无限大小原始数据 | 已确认 |
| D02-04 | AgentEvent 使用 `run_id + sequence` 决定顺序，时间戳不参与排序 | 已确认 |
| D02-05 | 每个 run 恰好有一个 completed、failed 或 cancelled 终止事件 | 已确认 |
| D02-06 | Model Port 使用异步输出流，非流式结果通过聚合统一实现 | 已确认 |
| D02-07 | Provider 输出由应用层转换为 AgentEvent，Provider 不负责 run 生命周期 | 已确认 |
| D02-08 | 协议初始主版本为 `"1"`，未知 type 和未知主版本明确拒绝 | 已确认 |
| D02-09 | 只支持安全的 `reasoning_summary_delta` 思考摘要；不展示原始思维链，默认不持久化、不写日志、不进入下一轮上下文 | 已确认 |
| D02-10 | 阶段 02 不增加 Web 或 CLI 聊天入口，只以假实现完成协议演示 | 已确认 |
| D02-11 | Web/Application 入口拒绝空白用户输入，返回 `message_empty`，不创建 Message、run、事件或模型请求 | 已确认 |
| D02-12 | 对外 `error` 后必须紧跟 `run_failed`；内部重试不发布 `error`；`retryable` 只表示用户能否重新发起 | 已确认 |
| D02-13 | Web 使用 Pydantic Schema 完成边界校验，再显式转换为标准库 Domain 对象；Pydantic 不进入 Domain | 已确认 |
| D02-14 | Session Store 阶段 02 不加入乐观并发版本，推迟至阶段 04 决定 | 已确认 |

## 21. 当前结论

阶段 02 设计、实现、自动化测试、质量检查和验收已经完成，当前没有未决设计条目。PRO-01 ～ PRO-08 的实际结果、覆盖率、设计偏差和验收决策已记录在 `completion-report.md`。

项目负责人已确认测试驱动的 Fake Model 协议闭环可以作为阶段 02 最小演示证据，阶段状态为“已完成/已验收”。下一步可以创建阶段 03 设计文档；设计确认前仍不开始千问接入或 Web 单轮聊天编码。
