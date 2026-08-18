# 阶段 03：千问接入与 Web 单轮聊天

> 状态：已实现；已测试；已验收
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-17
>
> 前置阶段：阶段 02“核心消息与事件协议”已验收
>
> 适用项目：NovaAgent
>
> 项目根目录：`/Users/jiaojie/NovaAgent`
>
> 编码许可：已开放；项目负责人于 2026-08-17 确认阶段 03 设计并允许开始编码

## 1. 背景与用户价值

阶段 01 建立了可安装、可配置、可诊断和可启动的工程地基，阶段 02 建立了与模型供应商和 Web 框架无关的消息、事件和 Port 协议。NovaAgent 现在能够使用 Fake Model 证明内部协议闭环，但还不能回答真实用户问题，也没有用户可操作的聊天页面。

阶段 03 要完成系统第一条真实外部能力闭环：用户在浏览器输入一段文本，NovaAgent 通过千问获取完整文本回答，再在同一页面显示回答、模型名称、耗时和使用量摘要。

后续范围变更：项目负责人于 2026-08-17 在阶段 04 验收后确认，千问成为 NovaAgent 唯一模型 Provider，豆包接入和模型多模态任务永久移出路线。阶段 03 中关于阶段 14 豆包接入的安排已被替代；现有豆包配置兼容面由进度矩阵 MOD-06 跟踪清理。

这一阶段的价值不是一次性建设完整控制台，而是验证以下架构判断：

1. 已确认的 `Message`、`ModelPort` 和 `AgentEvent` 能够承载真实 Provider，而不需要让领域层依赖 DashScope 数据结构。
2. Web 控制台能够成为唯一用户聊天入口，同时保持接口层只负责输入输出转换。
3. 缺失密钥、供应商鉴权失败、限流、超时和异常响应能够转换为稳定、脱敏且对用户有帮助的错误。
4. 后续流式输出、多轮会话和工具循环可以继续复用同一条应用调用链，而不是另建第二套聊天实现。

## 2. 当前能力与本阶段问题

### 2.1 已有能力

当前代码已经具备：

- 只允许 `qwen` 的 Provider 白名单。
- 从 `DASHSCOPE_API_KEY` 检查千问密钥是否存在的诊断能力。
- FastAPI 应用、健康检查、诊断 API、请求 ID 和本地/令牌两种 Web 鉴权模式。
- 不可变的 `Message`、`TextBlock`、`ModelRequest`、`ModelOutput` 和 `AgentEvent`。
- 异步 `ModelPort.stream()`；即使调用方需要完整回复，也通过统一输出协议聚合。
- `run_protocol()` 对文本、可选思考摘要、使用量、完成事件和失败事件的统一编排。
- Web Pydantic Schema 与标准库领域对象之间的显式转换边界。
- 空白输入使用 `message_empty` 拒绝，并向用户显示“请输入内容后再发送”。

### 2.2 当前缺口

当前系统还缺少：

- 真实千问 HTTP Adapter 和供应商响应解析。
- 面向真实 Provider 的错误类型、能力声明、超时、重试和并发限制。
- 将一条 Web 文本输入组织为单轮 `ModelRequest` 的应用服务。
- 将内部事件投影为非流式 HTTP 响应的生产消费者。
- `POST /api/v1/chat` 聊天 API。
- 可以在浏览器中完成输入、等待和结果展示的最小页面。
- 使用假 HTTP 服务验证千问协议，以及使用真实账号完成受控人工验收的证据。

## 3. 本阶段目标

阶段 03 设计并实现以下能力：

- MOD-01：接入千问 / DashScope 文本模型，实现首个真实 `ModelPort`。
- MOD-02：统一模型鉴权、限流、超时、请求拒绝、服务不可用和响应非法错误。
- MOD-03：记录模型名称、端到端耗时和输入/输出 token 使用量。
- MOD-04：定义并维护千问文本能力声明。
- MOD-05：拒绝自定义端点和非千问 Provider；阶段 03 的双 Provider 历史兼容面由 MOD-06 收敛。
- WEB-02（阶段 03 子范围）：实现非流式、无会话的单轮聊天 API。
- WEB-04（阶段 03 子范围）：实现只支持纯文本单轮问答的最小 Web 页面。
- ECO-01（阶段 03 子范围）：完成千问文本 Provider 的实际接入。
- ECO-05（阶段 03 子范围）：形成 Web 控制台唯一用户聊天入口的第一版。

阶段完成时必须可以执行以下真实闭环：

```text
浏览器文本输入
  → Web Schema 与输入限制
  → SingleTurnChatService
  → Message / ModelRequest
  → QwenModelAdapter
  → DashScope 官方 HTTP API
  → ModelOutput
  → AgentEvent / 非流式响应投影
  → 最终 Message
  → Web JSON 响应
  → 浏览器显示答案、模型、耗时和使用量
```

## 4. 非目标

本阶段明确不实现：

- 不接入豆包或任何第二模型 Provider；该限制已由后续范围变更确认为永久产品边界。
- 不接入 OpenAI、Claude、Gemini、DeepSeek、GLM、Kimi、MiniMax、自定义 Provider 或自定义兼容端点。
- 不实现 SSE、WebSocket 或供应商流式请求；阶段 04 再实现流式输出。
- 不实现多轮会话、会话列表、历史恢复、消息持久化或 SQLite。
- 不实现取消生成；阶段 04 随流式生命周期一起设计。
- 不实现工具定义、工具调用、工具执行或 Agent 决策循环。
- 不支持图片、音频、视频或任何模型多模态输入；该能力不再安排到后续阶段。
- 不实现 Markdown、代码高亮、产物卡片、工具卡片或完整控制台导航。
- 不允许用户从聊天请求中选择 Provider、模型、温度、最大 token 或供应商参数。
- 不在当前或后续 Web 页面提供 Provider API Key 的录入、修改、读取或持久化功能；千问 API Key 由服务端进程环境或未纳入 Git 的本地 `.env` 文件提供，进程环境变量优先。
- 不通过 CLI 增加聊天入口，也不建设终端聊天或第三方消息通道。
- 不保存消息、思考摘要或完整供应商响应，不建立聊天历史。
- 不展示、保存、记录或转发模型原始思维链。
- 不引入 DashScope Python SDK；本阶段使用现有 HTTPX 依赖直接适配官方 HTTP API。

## 5. 使用场景

### 5.1 正常单轮问答

用户打开 NovaAgent Web 页面，输入非空文本并点击“发送”。页面进入等待状态，后端只使用这一条用户消息调用千问。成功后页面显示完整回答、`qwen`、实际模型名称、耗时，以及供应商返回的输入和输出 token 数。

每次发送都是新的独立 run。第二次输入不会自动包含第一次问答，刷新页面也不恢复历史。

### 5.2 空白输入

用户输入空字符串、空格、换行或制表符时，页面先提示“请输入内容后再发送”。即使绕过前端直接调用 API，后端也返回 HTTP `422` 和稳定错误码 `message_empty`。

空白输入不会创建 `Message`、`run_id` 或事件，不调用千问，也不产生计费。

### 5.3 缺少千问密钥

NovaAgent 仍然能够启动，健康检查和诊断仍然可用。聊天请求返回 HTTP `503`、错误码 `secret_missing` 和不包含密钥名称以外敏感内容的操作提示。系统不得向 DashScope 发起请求。

`/health/ready` 表示 Web 服务能够接收诊断请求，不把缺少可选外部凭据视为整个进程未就绪；诊断端点单独报告千问凭据未配置。

Web 页面只显示“千问 API Key：已配置”或“千问 API Key：未配置”，不得提供输入框、保存按钮、编辑入口或任何能够读取原始值的接口。这个限制是 NovaAgent 的长期产品边界，不在后续 Web 控制台阶段解除。

### 5.4 令牌鉴权模式

当 Web 配置为 `auth_mode="token"` 时，聊天 API 必须要求 `X-NovaAgent-Token` 或 Bearer Token。最小页面提供令牌输入框，令牌只保存在当前页面的 JavaScript 内存中，不写入 URL、Cookie、`localStorage` 或日志。

页面外壳和静态资源可以公开加载，但聊天和诊断 API 继续受保护。鉴权失败返回 `authentication_required`，不能与千问 API 密钥错误混淆。

### 5.5 供应商暂时失败

当千问限流、连接失败、服务不可用或超时时，用户看到稳定中文提示和是否建议重试的信息。页面保留原输入，允许用户手动再次发送；不会显示供应商原始响应、请求头或堆栈。

## 6. 功能设计

### 6.1 单轮语义

“单轮”在本阶段定义为：

- 一次请求只接受一个字符串字段 `message`。
- 应用层只创建一个 `role=user` 的 `Message`。
- 不注入历史消息，不创建或读取 `session_id`。
- 不保存用户输入和模型回答。
- 一次请求只产生一个最终 assistant `Message`，或一个明确失败结果。
- 页面可以在内存中保留当前显示结果，但该显示状态不属于系统会话。

阶段 03 不添加临时会话概念。阶段 04 将基于 `SessionStorePort` 正式增加会话生命周期，避免以后兼容一个没有清晰语义的阶段 03 会话 ID。

### 6.2 输入规则

Web 请求必须满足：

- `Content-Type` 为 `application/json`。
- JSON 对象只允许 `message` 字段，未知字段拒绝。
- `message` 必须是字符串。
- 去除首尾空白后为空时返回 `message_empty`，但合法输入的原始首尾空白不自动修改。
- `message` 最多包含 32,000 个 Unicode 字符；超限返回 `message_too_long`。
- 整个 HTTP 请求体最多 64 KiB；超限返回 `request_too_large`。

字符限制用于给用户明确反馈，请求体限制用于防止在 JSON 解析前消耗无界内存。两者必须分别测试。

### 6.3 输出规则

成功响应包含：

- 协议主版本。
- 本次执行的 `run_id`。
- 使用阶段 02 `MessageSchema` 序列化的最终 assistant 消息。
- 固定 Provider 名称 `qwen` 和实际配置模型名。
- 端到端应用耗时 `latency_ms`。
- 可选的输入、输出和合计 token；供应商未返回合法使用量时为 `null`，不能伪造为零。

HTTP 响应不返回内部事件数组、供应商响应对象、供应商请求体、密钥或原始异常。

### 6.4 最小页面

页面只包含本阶段闭环需要的元素：

- NovaAgent 标题和“千问单轮聊天”范围说明。
- 多行文本输入框。
- 发送按钮和清空按钮。
- 等待、成功和失败状态。
- 使用纯文本方式展示的回答，保留换行但不解析 HTML。
- Provider、模型、耗时、输入 token、输出 token 和合计 token。
- 千问 API Key 的“已配置/未配置”状态；页面永远不接收或显示 API Key 原值。
- 在令牌鉴权模式下可填写的 Web Token 输入框。
- “当前不保存历史，每次发送都是独立对话”的提示。

前端必须使用 `textContent` 或等价安全 API 写入用户输入和模型输出，不使用 `innerHTML`。阶段 03 不引入前端框架、CDN、Markdown 解析器或构建工具。

### 6.5 思考摘要

阶段 02 已确认：只有 Provider 提供明确、独立且允许面向用户展示的安全摘要时，才能映射 `reasoning_summary_delta`；不得把原始思维链当作摘要。

阶段 03 的推荐决定是：

- 千问能力声明中 `reasoning_summary=false`。
- 请求显式关闭 thinking；Adapter 不把 `reasoning_content`、隐藏推理字段或普通答案的一部分映射为思考摘要。
- 即使供应商意外返回推理字段，也只丢弃，不记录、不持久化、不进入响应。
- 最小页面不渲染空的“思考摘要”区域。
- 后续如果千问提供文档明确、可安全展示的摘要能力，必须单独设计和验收，不能仅根据字段名称直接开放。

这样既保留阶段 02 的可扩展协议，又不把模型原始推理错误地包装成产品功能。

### 6.6 使用量与耗时

使用量从 DashScope OpenAI-compatible 响应的 `prompt_tokens` 和 `completion_tokens` 映射为 `TokenUsage.input_tokens` 与 `TokenUsage.output_tokens`。合计值由 NovaAgent 使用两者相加得到，不信任供应商返回的矛盾合计值。

耗时使用单调时钟从应用服务开始处理合法输入到获得最终结果为止，包含本地编排、等待重试和 Provider 网络时间，不使用系统墙上时间相减。日志和 HTTP 响应中使用非负整数毫秒。

## 7. 架构与模块设计

### 7.1 依赖方向

```text
interfaces/web
  ChatRequestSchema / ChatResponseSchema / HTML + JS
                    ↓
application/chat
  SingleTurnChatService / SingleTurnEventProjection
                    ↓
domain
  Message / ModelRequest / ModelPort / AgentEvent / model errors
                    ↑
infrastructure/models/qwen
  QwenModelAdapter / HTTP response mapper / retry policy
                    ↑
bootstrap
  Settings / credential resolver / HTTP client lifecycle / dependency assembly
```

必须保持：

1. Application 不导入 HTTPX、FastAPI 或 DashScope JSON Schema。
2. Qwen Adapter 不创建 HTTP 响应，也不知道 Web 状态码。
3. Web 不直接调用 Qwen Adapter，只调用 `SingleTurnChatService`。
4. Provider 的 HTTP 对象和原始 JSON 不离开 Infrastructure。
5. Bootstrap 只装配依赖和生命周期，不实现聊天规则。

### 7.2 模块落点

拟定新增或修改以下最小模块：

```text
src/novaagent/
├── domain/
│   ├── errors.py                    # 新增稳定模型错误
│   ├── models.py                    # ModelCapabilities / ProviderDescriptor
│   └── ports.py                     # 复用 ModelPort；必要时只做兼容扩展
├── application/
│   └── chat/
│       ├── __init__.py
│       └── single_turn.py            # SingleTurnChatService 与响应投影
├── infrastructure/
│   └── models/
│       └── qwen/
│           ├── __init__.py
│           ├── adapter.py            # ModelPort 实现
│           ├── mapper.py             # 领域消息与 DashScope JSON 转换
│           └── retry.py              # 小型可测试重试策略；不做通用框架
├── interfaces/
│   └── web/
│       ├── app.py                    # 页面、聊天路由、错误映射、安全头
│       ├── chat_protocol.py          # Chat HTTP Schema
│       └── static/
│           ├── index.html
│           ├── app.js
│           └── styles.css
└── bootstrap/
    └── container.py                  # HTTP client lifespan 和依赖装配

tests/
├── unit/
│   ├── test_single_turn_chat.py
│   ├── test_qwen_mapper.py
│   └── test_qwen_retry.py
├── contract/
│   └── test_qwen_model_port.py
├── integration/
│   ├── test_qwen_adapter.py
│   └── test_web_chat.py
└── end_to_end/
    └── test_web_single_turn.py
```

如果实现时证明 `mapper.py` 或 `retry.py` 只有少量私有函数，应合并进 `adapter.py`，不为了匹配目录草图制造空模块。

### 7.3 HTTP 客户端生命周期

Bootstrap 使用 FastAPI lifespan 创建并关闭一个进程级 `httpx.AsyncClient`：

- 复用连接池，不为每次聊天新建客户端。
- `max_connections` 和 `max_keepalive_connections` 与千问最大并发配置一致。
- Adapter 通过构造函数接收客户端，测试时注入 `httpx.MockTransport`。
- 关闭应用时等待客户端正常关闭。
- 不修改 `dashscope.api_key`、环境全局客户端或其他全局可变状态。

### 7.4 非流式响应投影

`run_protocol()` 继续产生统一 `AgentEvent`，阶段 03 不绕开事件协议直接拼 Web 响应。

Application 新增 `SingleTurnEventProjection`，它是生产事件消费者而不是测试 Fake：

- 从 `run_started` 记录 `run_id`。
- 从 `run_completed` 记录可选 `TokenUsage`。
- 不缓存完整事件列表。
- 不保存用户消息、最终回答或思考摘要。
- 对失败事件不做第二套错误决策，异常仍由应用服务向上抛出。

阶段 04 可以将该投影替换或组合为 Web 流式 Sink，不需要改变 Qwen Adapter 或核心聊天输入。

## 8. 核心接口和数据结构

### 8.1 应用服务

拟定接口：

```python
@dataclass(frozen=True, slots=True)
class SingleTurnChatResult:
    run_id: str
    message: Message
    provider: str
    model: str
    usage: TokenUsage | None
    latency_ms: int


class SingleTurnChatService:
    async def chat(self, text: str) -> SingleTurnChatResult: ...
```

服务职责：

1. 使用阶段 02 的 `create_user_message()` 校验空白并创建用户消息。
2. 使用配置生成 `ModelOptions`，不接受 Web 请求覆盖。
3. 只把这一条用户消息放入 `ModelRequest`，`tools=()`。
4. 调用 `run_protocol()`，由响应投影取得 run 和 usage。
5. 使用单调时钟计算耗时并返回不可变结果。

### 8.2 千问能力声明

拟定能力对象至少表达：

| 字段 | 阶段 03 千问值 | 说明 |
| --- | --- | --- |
| `provider` | `qwen` | 稳定内部名称 |
| `model` | 配置值 | 默认 `qwen3.8-max` |
| `text_input` | `true` | 只支持 TextBlock |
| `text_output` | `true` | 必须产生有意义文本 |
| `native_streaming` | `false` | 阶段 04 再开放 |
| `tool_calling` | `false` | 阶段 05 再开放；阶段 05 已实现 |
| `reasoning_summary` | `false` | 不把原始思维链当摘要 |
| `image_input` | `false` | 永久不开放模型图片输入 |
| `audio_input` | `false` | 永久不开放模型音频输入 |
| `usage` | `true` | 运行时仍允许供应商偶发缺失 |

能力声明描述“NovaAgent 当前已经实现并验收的能力”，不直接照抄供应商营销能力。工具能力必须等对应阶段完成后才能改为 `true`；图片和音频输入保持 `false`，不进入后续路线。

### 8.3 千问请求映射

阶段 03 固定调用阿里云百炼中国大陆官方 OpenAI-compatible 地址：

```text
POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

端点不进入用户配置，不允许自定义 URL，避免把 Provider 配置变成任意网络出口或第三方兼容 Provider。

请求头：

```text
Authorization: Bearer <DASHSCOPE_API_KEY>
Content-Type: application/json
```

请求体语义：

```json
{
  "model": "qwen3.8-max",
  "messages": [
    {"role": "user", "content": "用户原始文本"}
  ],
  "stream": false,
  "enable_thinking": false,
  "temperature": 0.7,
  "max_tokens": 2048
}
```

具体可选字段只在配置值非空时发送。阶段 03 不发送 `tools`、`tool_choice`、图片内容、供应商扩展 metadata 或会话标识。

Adapter 必须拒绝：

- 空 `messages`。
- 非 TextBlock 输入。
- `tool` 消息或包含 ToolCall/ToolResult 的消息。
- 非空 `ModelRequest.tools`。
- 供应商不支持的请求选项。

这些拒绝表示调用方违反已声明能力，必须在网络请求前发生。

### 8.4 千问响应映射

成功响应只读取：

- `choices[0].message.content`：必须是非空文本。
- `choices[0].tool_calls`：本阶段若存在则视为不兼容响应，不执行工具。
- `usage.prompt_tokens` 和 `usage.completion_tokens`：存在时必须是非负整数。
- 供应商 request ID：只允许作为脱敏诊断关联值写入结构化日志，不进入领域消息。

一次非流式响应通过 `ModelPort.stream()` 依次 yield：

1. 一个 `TextModelDelta`。
2. 如果使用量合法存在，再 yield 一个 `UsageModelOutput`。

`reasoning_content`、隐藏推理或其他未识别字段不映射为输出，也不记录。未知响应字段遵循边界兼容规则忽略，但已依赖字段缺失、类型错误或空文本必须产生 `provider_response_invalid`。

### 8.5 Web API

请求：

```http
POST /api/v1/chat
Content-Type: application/json
X-NovaAgent-Token: <仅 token 模式需要>

{"message":"你好，请介绍一下你自己。"}
```

成功响应：

```json
{
  "protocol_version": "1",
  "run_id": "run-...",
  "message": {
    "protocol_version": "1",
    "message_id": "msg-...",
    "role": "assistant",
    "content": [{"type": "text", "text": "..."}],
    "created_at": "2026-08-17T00:00:00Z",
    "metadata": {}
  },
  "provider": {"name": "qwen", "model": "qwen3.8-max"},
  "usage": {
    "input_tokens": 12,
    "output_tokens": 28,
    "total_tokens": 40
  },
  "latency_ms": 842
}
```

错误响应统一为：

```json
{
  "error": {
    "code": "provider_rate_limited",
    "message": "千问请求过于频繁，请稍后重试",
    "request_id": "...",
    "retryable": true,
    "field": null
  }
}
```

`field` 没有值时可以省略。所有成功和失败响应继续返回 `X-Request-ID`。

## 9. 数据流与执行流程

### 9.1 成功流程

```text
1. 浏览器 POST /api/v1/chat
2. 请求体大小、Content-Type、鉴权和 Schema 校验
3. SingleTurnChatService.chat(raw_text)
4. create_user_message() 创建 Message
5. 形成 ModelRequest(messages=(user_message,), tools=())
6. run_protocol() 发布 run_started / message_started
7. QwenModelAdapter 检查凭据、能力和并发额度
8. Adapter 通过固定官方端点调用千问
9. 响应映射为 TextModelDelta + UsageModelOutput
10. run_protocol() 发布 text_delta / message_completed / run_completed
11. SingleTurnEventProjection 取得 run_id 和 usage
12. Service 返回 SingleTurnChatResult
13. Web 将最终 Message 显式转换为 JSON
14. 浏览器安全显示文本、模型、耗时和使用量
```

### 9.2 失败流程

```text
Provider/Transport 异常
  → Qwen Adapter 分类为稳定 ModelProviderError
  → 允许的内部重试（不发布 error）
  → 重试耗尽
  → run_protocol 发布 error
  → 紧接 run_failed
  → 应用服务抛出稳定异常
  → Web 映射 HTTP 状态和安全错误体
  → 页面显示提示并保留原输入
```

空白、过长、请求体超限和鉴权失败发生在调用模型之前，不创建 run，也不产生内部错误事件。

### 9.3 无会话保证

本阶段不得调用 `SessionStorePort`。日志、投影和页面状态均不能被误称为会话存储。该约束通过应用集成测试和依赖测试验证。

## 10. 配置和运行方式

### 10.1 配置模型

阶段 03 建议将千问配置明确为：

```toml
[providers]
default = "qwen"
enabled = ["qwen"]

[providers.qwen]
model = "qwen3.8-max"
temperature = 0.7
max_output_tokens = 2048
timeout_seconds = 60
max_retries = 1
max_concurrency = 4
```

约束：

- `providers.default` 始终必须为 `qwen`。
- 当前目标中 `enabled` 只能是 `["qwen"]`；阶段 03 已验收代码仍识别豆包的历史兼容面，待 MOD-06 删除。
- 千问模型名必须以 `qwen` 开头，最长 128 字符，只接受小写字母、数字、点、下划线和连字符；默认值 `qwen3.8-max` 符合该规则。
- `temperature` 范围为 `0..2`。
- `max_output_tokens` 范围为 `1..32768`。
- `timeout_seconds` 范围为 `1..300`。
- `max_retries` 范围为 `0..2`，默认 `1` 表示初次请求失败后最多再尝试一次。
- `max_concurrency` 范围为 `1..32`。
- 不提供 `base_url`、任意 headers、代理、组织 ID或自定义 Provider 配置。

阶段 03 已验收代码仍可识别和诊断豆包配置，但不会实例化或调用豆包。该行为属于待删除的历史兼容面，不代表产品支持。

### 10.2 密钥

千问密钥在服务启动时从服务端运行时环境快照读取。运行时环境可以来自进程环境或项目目录下未纳入 Git 的本地 `.env` 文件，进程环境变量优先：

```text
DASHSCOPE_API_KEY
```

密钥不得写入 TOML、源码、浏览器、诊断响应、异常消息、日志或测试快照。Adapter 在真正发起请求前解析密钥；缺失时立即抛出 `secret_missing`。本地开发可以把密钥放入项目目录下 Git 忽略的 `.env`，生产或其他部署也可以通过进程环境提供；每次进程启动时重新解析，不把密钥写入 NovaAgent 管理的数据目录。

`DASHSCOPE_API_KEY` 的配置入口是服务端进程环境或 Git 忽略的本地 `.env` 文件；可通过 `--env-file /path/to/.env` 或 `NOVAAGENT_ENV_FILE` 指定其他本地文件。`.env` 只允许密钥相关键，普通应用配置继续使用 TOML 或 `NOVAAGENT_*` 环境变量。当前和后续 Web 控制台都只读取后端返回的布尔配置状态，不提供 API Key 的录入、修改、删除、读取或持久化能力，也不规划 Keychain 或其他由 Web 驱动的密钥管理方案。`NOVAAGENT_WEB_TOKEN` 是 Web 访问凭据，与千问 API Key 不同，仍按照 Web 鉴权规则单独处理。

### 10.3 超时、重试和并发

推荐规则：

- 连接超时：5 秒。
- 读取/整体模型等待上限：使用 `timeout_seconds`，默认 60 秒。
- 同一进程最多同时运行 `max_concurrency` 个千问请求，默认 4。
- 并发额度最多等待 1 秒；无法取得时返回 `provider_busy`，不向供应商发请求。
- 最多自动重试 `max_retries` 次，默认 1 次。
- 只自动重试建立连接前失败、HTTP `429`、`502`、`503` 和 `504`。
- 已发送请求后的读取超时不自动重试，避免同一提示被重复计费；由用户决定是否重新发起。
- 认证、权限、输入、模型配置和其他 `4xx` 不重试。
- 重试间隔采用带抖动的短退避；供应商提供合法 `Retry-After` 时遵守，但单次等待最多 2 秒。
- 内部重试不产生对外 `error` 事件；只有最终失败才发布 `error → run_failed`。

阶段 03 不建设可配置的每分钟 token bucket。供应商配额会因账号和模型不同，固定本地 QPS 容易给出错误保证；当前通过并发上限、上游 `429` 分类和有限重试建立基础保护，正式限额策略留待真实运行数据出现后设计。

### 10.4 启动与人工配置

服务仍使用：

```text
uv run novaagent serve
```

真实验收前由负责人以安全方式通过服务端进程环境或未纳入 Git 的本地 `.env` 文件提供 `DASHSCOPE_API_KEY`。文档和完成报告只能记录“已配置/未配置”，不得记录密钥值。

## 11. 异常、安全与边界情况

### 11.1 稳定错误与 HTTP 映射

| 错误码 | HTTP | 可重试 | 触发条件 | 用户提示方向 |
| --- | ---: | --- | --- | --- |
| `message_empty` | 422 | 否 | 输入仅为空白 | 请输入内容后再发送 |
| `message_too_long` | 422 | 否 | 超过 32,000 字符 | 缩短输入后重试 |
| `request_invalid` | 422 | 否 | JSON/字段/类型非法 | 检查请求格式 |
| `request_too_large` | 413 | 否 | 请求体超过 64 KiB | 缩小请求内容 |
| `authentication_required` | 401 | 否 | Web Token 缺失或错误 | 提供正确 Web Token |
| `secret_missing` | 503 | 否 | 未配置 `DASHSCOPE_API_KEY` | 配置千问密钥后重试 |
| `provider_authentication_failed` | 502 | 否 | DashScope 返回 401/403 | 检查千问密钥和权限 |
| `provider_rate_limited` | 429 | 是 | DashScope 返回 429 且重试耗尽 | 稍后重试 |
| `provider_timeout` | 504 | 是 | 连接或读取超时 | 稍后重试 |
| `provider_busy` | 503 | 是 | 本地并发额度已满 | 等待当前请求结束 |
| `provider_model_invalid` | 503 | 否 | 模型不存在或不兼容 | 检查模型配置 |
| `provider_input_rejected` | 422 | 否 | 供应商明确拒绝输入 | 修改输入 |
| `provider_unavailable` | 503 | 是 | 网络或供应商 5xx | 稍后重试 |
| `provider_response_invalid` | 502 | 是 | 成功响应缺少合法文本或结构错误 | 稍后重试并检查日志关联 ID |
| `internal_error` | 500 | 否 | 未分类内部错误 | 使用请求 ID 诊断 |

Web 鉴权失败使用 `401`；千问密钥无效使用 `502`，防止浏览器把 Provider 凭据问题误解为当前用户需要重新登录。

### 11.2 供应商错误解析

Adapter 可以读取 HTTP 状态、供应商稳定错误码、request ID 和合法 `Retry-After`，但不得把供应商原始错误消息直接发送给用户。对未知错误码按 HTTP 状态安全回退。

日志最多记录：

- NovaAgent request ID 和 run ID。
- Provider `qwen` 与配置模型名。
- HTTP 状态和稳定内部错误码。
- 供应商 request ID 的脱敏关联值。
- 尝试次数、耗时和使用量。

日志不得记录：

- Authorization 或任何请求头完整值。
- `DASHSCOPE_API_KEY`。
- 用户完整输入、模型完整回答或原始请求体。
- 供应商完整错误正文或响应正文。
- `reasoning_content` 或其他隐藏推理字段。

### 11.3 Web 安全

- 保持同源访问，不启用宽泛 CORS。
- 非 loopback 绑定继续强制 `auth_mode="token"`。
- 页面外壳公开，但聊天和诊断 API 必须鉴权。
- Token 只保存在页面内存，页面刷新后需要重新输入。
- 不把 Token 放入 query string、Cookie、DOM 文本或持久存储。
- JSON API 和自定义认证头避免 Cookie 型 CSRF；不增加 Cookie 登录。
- 对配置 host 使用可信 Host 校验，降低本地服务 DNS rebinding 风险。
- 添加 `Content-Security-Policy`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer` 和禁止 framing 的响应头。
- 静态页面不加载外部脚本、字体、图片或 CDN 资源。
- 前端只以文本方式渲染回答，模型返回的 HTML/脚本不得执行。

### 11.4 进程与资源边界

- 每个 HTTP 请求只允许一次活动模型调用。
- 并发门禁在建立供应商请求前取得，并在成功、失败、取消或异常时通过 `finally` 释放。
- HTTP 客户端在应用 lifespan 关闭，测试验证没有未关闭连接警告。
- 请求断开在阶段 03 不承诺取消已经发出的非流式供应商调用；阶段 04 随取消状态机解决。后端仍受读取超时限制。
- 不记录或持久化响应正文，完成 HTTP 响应后只留下脱敏结构化运行指标。

## 12. 测试方案

### 12.1 配置单元测试

- 默认千问模型和各运行参数正确。
- 阶段 03 默认 Provider 必须为 `qwen`。
- `enabled` 不包含 qwen 时拒绝聊天配置。
- 非 `qwen` 前缀模型、非法字符和超长模型名拒绝。
- temperature、token、timeout、retry 和 concurrency 上下界。
- 配置 Schema 继续拒绝 base URL、自定义 headers 和第三家 Provider。
- 配置错误不回显环境变量值。

### 12.2 应用服务单元测试

- 合法文本形成单条 user Message 和无工具 ModelRequest。
- 原始合法空白格式不被自动裁剪。
- 空白输入不调用 ModelPort、不创建 run。
- 每次调用生成独立 message/run ID，不使用 SessionStore。
- 成功结果包含最终 Message、Provider、模型、usage 和非负耗时。
- usage 缺失时返回 `null` 而不是零。
- 模型异常保持稳定错误类型。
- 响应投影不保存完整事件或思考摘要。

### 12.3 千问映射单元测试

- TextBlock 正确转换为 DashScope message。
- 非文本、工具、空消息和不支持选项在发网前拒绝。
- 固定 URL、Authorization、`stream=false` 和 `enable_thinking=false`。
- 文本与 usage 正确映射为 ModelOutput。
- `reasoning_content` 被丢弃且不进入日志或输出。
- 空 choices、空 content、非法 usage 和意外 tool_calls 明确失败。
- 未知可选字段不破坏合法响应。

### 12.4 错误与重试测试

- 缺少密钥时零 HTTP 请求。
- 401/403、429、各类 4xx、5xx 和无效 JSON 的稳定分类。
- 连接失败和允许状态最多重试配置次数。
- 读取超时不自动重试。
- `Retry-After` 解析、2 秒上限和非法值回退。
- 认证、输入和模型配置错误不重试。
- 内部尝试不发布 error；耗尽后只发布一次 `error → run_failed`。
- 异常路径始终释放并发额度。

### 12.5 Web 集成测试

- `GET /` 返回最小 HTML，静态资源和安全响应头正确。
- local 模式可以调用聊天 API。
- token 模式无令牌、错误令牌和正确令牌行为。
- 空白、过长、未知字段、非法 JSON、错误 Content-Type 和超大 body。
- 成功响应符合 Chat Schema，并复用 Message Schema。
- 所有错误符合统一错误信封并包含 request ID。
- 回答中的 `<script>` 只作为文本数据返回；前端脚本不使用 `innerHTML`。
- `/health/live` 和 `/health/ready` 在无千问密钥时仍可用。
- 诊断只报告凭据存在状态，不泄露值。
- Web 页面只显示千问 API Key 的“已配置/未配置”状态，不存在 Provider 密钥输入、保存、编辑或删除控件。
- 根端点原有阶段 01 JSON 占位测试更新为页面测试。

### 12.6 契约与端到端测试

- 用 `httpx.MockTransport` 模拟官方 API，不访问互联网即可验证真实 Adapter。
- Qwen Adapter 满足 `ModelPort` 契约，只输出领域 `ModelOutput`。
- Fake Qwen HTTP → ChatService → AgentEvent → Web JSON 的完整集成闭环。
- 浏览器最小人工检查覆盖输入、等待、成功元信息、失败提示和清空操作。
- 真实千问 API 只用于明确启用的人工验收，不进入默认 Pytest 或 CI，不在测试输出记录输入和回答全文。

### 12.7 质量门禁

- 新增聊天、错误映射和 Qwen Adapter 核心模块覆盖率不低于 90%。
- 项目总覆盖率不低于 80%。
- Pytest、Ruff lint、Ruff format、Mypy 和 `novaagent doctor` 全部通过。
- 阶段 01、02 既有测试全部通过。
- `git diff --check` 通过。

## 13. 验收标准

### 13.1 功能验收

- 浏览器能发送一条非空文本并看到真实千问完整回答。
- 页面显示 Provider、配置模型、耗时和使用量；usage 缺失时明确显示“未提供”。
- 每次请求为独立单轮，不携带之前消息。
- 空白输入前后端都有清晰中文提示，且不调用模型。
- 缺少或无效密钥、限流、超时和服务错误呈现为稳定、安全的错误。

### 13.2 架构验收

- Domain 和 Application 不导入 HTTPX、FastAPI 或供应商 SDK。
- Web 不直接调用 Qwen Adapter。
- 千问实现可被 Fake Model 或 MockTransport 替换。
- Qwen HTTP/JSON 对象不越过 Infrastructure 边界。
- 聊天应用流程继续产生统一 AgentEvent，没有单独的“普通聊天协议”。
- 没有生产 Fake、全局 SDK 密钥修改或自定义 Provider 注册入口。

### 13.3 安全验收

- 密钥不出现在配置文件、页面、日志、诊断、异常、快照或 Git diff 中。
- 用户输入、模型回答和思维链默认不写日志。
- Web 页面和 Web API 不能接收、修改、返回或持久化千问 API Key，只能显示配置状态。
- 非 loopback Web 必须启用 Token 鉴权。
- Token 不通过 URL、Cookie 或浏览器持久存储传递。
- 超大请求、并发过载和供应商长时间无响应有明确上限。
- Provider 输出不能通过 HTML 注入执行脚本。

### 13.4 测试与运行验收

- 自动化质量门禁全部通过。
- 假 HTTP 集成演示可重复运行。
- 使用负责人提供的真实千问账号完成一次受控 Web 单轮演示。
- 完成报告记录使用的模型名、时间、成功/失败、耗时和 usage 是否可用，但不记录密钥或完整聊天内容。
- 项目负责人确认演示和设计偏差后，阶段 03 才能标记“已完成/已验收”。

## 14. 最小演示方案

### 14.1 可重复的无网络演示

通过集成测试启动 NovaAgent，使用 `httpx.MockTransport` 返回一个与 DashScope 协议一致的响应：

```text
Web 请求
  → SingleTurnChatService
  → QwenModelAdapter
  → MockTransport
  → ModelOutput / AgentEvent
  → ChatResponse JSON
```

演示必须断言模型、回答、usage、耗时字段、run ID 和请求参数，不把“测试仅通过”替代真实验收。

### 14.2 真实 Web 演示

1. 安全地通过服务端进程环境或未纳入 Git 的本地 `.env` 文件向 NovaAgent 提供 `DASHSCOPE_API_KEY`。
2. 使用默认 loopback 地址启动 Web 服务。
3. 浏览器打开首页，确认页面说明为单轮聊天。
4. 输入一条容易核对且不包含敏感信息的问题。
5. 确认页面显示真实回答、`qwen`、模型名、耗时和 usage。
6. 再发送一条依赖上一轮信息的问题，确认页面明确提示单轮语义，且系统没有隐式携带历史。
7. 发送空白输入，确认不产生网络调用并提示重新输入。
8. 临时移除测试进程的密钥或使用隔离配置，确认聊天失败但健康和诊断仍可用。

真实演示会产生外部网络请求和可能的少量模型费用，因此必须在实现完成后由项目负责人明确提供可用凭据并同意执行；CI 不自动调用真实 API。

## 15. 实施任务清单

设计确认后按以下顺序实施：

| 编号 | 任务 | 完成条件 |
| --- | --- | --- |
| S03-01 | 扩展模型配置和校验 | 默认值、边界和白名单测试通过 |
| S03-02 | 增加模型能力与稳定错误 | Domain 无供应商/HTTP 类型，错误映射明确 |
| S03-03 | 实现 Qwen 请求/响应 Mapper | 全部合法与失败路径单测通过 |
| S03-04 | 实现 QwenModelAdapter | MockTransport 契约、超时和重试通过 |
| S03-05 | 实现 SingleTurnChatService | 单轮、事件投影和无 SessionStore 测试通过 |
| S03-06 | 完善 Bootstrap 生命周期 | HTTP client 正常创建、注入和关闭 |
| S03-07 | 实现 Chat HTTP Schema 与 API | 成功/错误契约和鉴权测试通过 |
| S03-08 | 实现最小静态页面 | 输入、状态、纯文本结果和元信息可用 |
| S03-09 | 补充安全限制 | 大小、并发、Host、安全头和脱敏测试通过 |
| S03-10 | 完成自动化验证 | Pytest、覆盖率、Ruff、Mypy、doctor 全通过 |
| S03-11 | 完成假 HTTP 演示 | 可重复、无网络、证据写入完成报告 |
| S03-12 | 完成真实千问 Web 验收 | 经负责人授权，记录脱敏结果和设计偏差 |
| S03-13 | 更新文档与进度矩阵 | completion-report、路线和能力状态一致 |

实施期间如果需要改变 API、错误码、思考摘要、安全边界或真实验收方式，必须先更新本文并重新确认相关决策。

## 16. 现有 CowAgent 参考与复用策略

### 16.1 可参考内容

只读参考项目中的以下内容有价值：

- `models/dashscope/dashscope_bot.py`：模型名处理、文本 content 可能出现不同形态、usage 字段和供应商错误场景。
- `models/dashscope/dashscope_session.py`：旧系统曾经需要处理 token 和会话裁剪，作为阶段 04 的行为参考。
- `channel/web/web_channel.py`：Web 鉴权、浏览器入口、请求错误和会话交互的用户场景。
- `channel/web/chat.html`：用户对聊天页面的基础操作习惯。

### 16.2 选择性复用

可以复用的是经过重新验证的边界经验和测试场景，例如：

- DashScope 成功响应的文本与 usage 读取场景。
- 供应商失败需要有限重试和友好提示的用户需求。
- Web 页面必须在鉴权失败、模型失败和等待期间保持明确状态。
- 模型名称与供应商实际响应可能存在差异时，以受控配置作为展示基准。

### 16.3 不复用内容

不复制或延续：

- `dashscope.api_key` 和 `os.environ` 的运行时全局修改。
- 同一个 Bot 同时管理配置、会话、供应商调用、重试和用户 Reply 的结构。
- 将异常捕获为统一“我现在有点累了”且丢失稳定错误分类的行为。
- 同步递归重试和无法区分请求是否已经发送的重试方式。
- 把用户完整 query、会话消息和完整回答写入 debug 日志。
- 旧 `Reply`、`Context`、`Bot` 或 Web Channel 对象进入新领域协议。
- 多模态、工具调用、会话命令、插件事件和动态配置刷新逻辑。
- DashScope SDK 依赖和供应商响应对象向上层传播。

## 17. 预期差异

| 方面 | CowAgent 参考实现 | NovaAgent 阶段 03 |
| --- | --- | --- |
| 调用方式 | DashScope SDK、部分全局状态 | 固定官方 HTTP API + 注入 AsyncClient |
| 密钥 | 配置读取后可能写入全局环境/SDK | 只从环境解析，不修改全局状态 |
| 聊天职责 | Bot 同时管理会话和回复 | Web → Application → ModelPort 分层 |
| 会话 | 单轮路径仍可能经过 SessionManager | 明确无 session、无历史、无持久化 |
| 错误 | 多种失败收敛为模糊回复 | 稳定错误码、HTTP 映射和 retryable |
| 重试 | 同步递归、广泛重试 | 有限异步策略，避免读取超时重复计费 |
| 日志 | 可能记录完整 query/reply | 默认只记录脱敏元数据和关联 ID |
| 推理 | 旧 Agent 路径可能处理 thinking 字段 | 阶段 03 禁用并丢弃原始推理 |
| Provider | 旧系统包含多个模型入口 | 只允许并调用千问 |
| Web | 大型既有页面和多类接口 | 无框架、无 CDN 的最小单轮页面 |
| 输出协议 | Reply/字典与不同调用链 | 统一 Message、ModelOutput、AgentEvent |

旧配置不在本阶段自动导入。若未来提供导入器，只允许导入千问模型名、Web 绑定和白名单内配置；旧密钥仍应通过安全环境配置，不复制进新 TOML。

## 18. 设计决策记录

以下设计决策已由项目负责人于 2026-08-17 整体确认，并作为阶段 03 实现依据。

| 编号 | 推荐决策 | 状态 |
| --- | --- | --- |
| D03-01 | 阶段 03 只实现千问文本；豆包真实接入保留到阶段 14 | 已被替代 |
| D03-02 | 使用 HTTPX 适配 DashScope 官方 OpenAI-compatible API，不引入供应商 SDK | 已确认 |
| D03-03 | 官方 Base URL 固定为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，由 Adapter 追加 `/chat/completions`，不开放自定义 base URL | 已确认 |
| D03-04 | 阶段 03 Provider 默认值和聊天选择固定为 qwen，默认模型为 `qwen3.8-max` | 已确认 |
| D03-05 | 单轮请求只含当前 user 文本，不创建 session、不保存消息 | 已确认 |
| D03-06 | Provider 非流式 HTTP 响应仍通过 ModelPort 输出和 AgentEvent 聚合 | 已确认 |
| D03-07 | API 使用 `POST /api/v1/chat`，输入只有 `message`，调用方不能覆盖模型参数 | 已确认 |
| D03-08 | 请求最多 64 KiB，message 最多 32,000 个 Unicode 字符 | 已确认 |
| D03-09 | 千问思考能力关闭，原始 reasoning 字段丢弃且不展示、不记录 | 已确认 |
| D03-10 | usage 缺失时返回 null，不伪造零；耗时以应用层单调时钟计算 | 已确认 |
| D03-11 | 自动重试最多一次，只覆盖安全的连接失败、429 和部分 5xx；读取超时不自动重试 | 已确认 |
| D03-12 | 默认并发上限为 4，不建设固定本地 QPS token bucket | 已确认 |
| D03-13 | 无千问密钥时服务仍健康/可诊断，但聊天返回 secret_missing | 已确认 |
| D03-14 | 页面公开加载，Chat/Diagnostics API 继续鉴权；Web Token 只保存在页面内存 | 已确认 |
| D03-15 | 页面以纯文本渲染回答，不引入 Markdown、CDN 或前端框架 | 已确认 |
| D03-16 | 真实 API 仅在负责人提供凭据并授权后人工验收，默认测试和 CI 全部使用 MockTransport | 已确认 |
| D03-17 | `DASHSCOPE_API_KEY` 由服务端进程环境或未纳入 Git 的本地 `.env` 文件提供；当前和后续 Web 只显示配置状态，不建设 Provider 密钥管理功能 | 已确认（修订） |
| D03-18 | 千问是唯一模型 Provider；取消豆包接入和模型多模态路线 | 已确认（后续范围变更） |

## 19. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 官方 API 或字段变化 | Mapper 边界集中、MockTransport 契约测试、非法响应稳定失败 |
| 模型名支持能力不一致 | 阶段能力声明按已实现能力，不根据模型宣传自动开放；默认使用 qwen3.8-max |
| 超时后自动重试造成重复计费 | 已发送请求的读取超时不自动重试，提示用户决定 |
| 上游限流导致重试风暴 | 最多一次重试、短退避、并发门禁和 Retry-After 上限 |
| 密钥或提示词泄漏 | 固定日志白名单、错误脱敏、测试扫描、禁止完整请求/响应日志 |
| 原始思维链误当摘要 | 关闭 thinking，丢弃 reasoning 字段，能力声明为 false |
| 阶段 03 临时页面变成永久架构 | 页面只依赖稳定 Chat API；阶段 04、07 渐进增强而非复制后端 |
| 为阶段 04 提前建设会话 | 明确不使用 SessionStore，不产生临时 session_id |
| 浏览器输出注入 | textContent、CSP、无 CDN、无 innerHTML |
| 本地服务被恶意网页访问 | 同源 JSON、自定义认证头、Host 校验、非 loopback 强制 Token |
| 没有真实密钥导致无法验收 | 自动化完成可控证据；负责人已完成真实 Web 演示并确认验收 |

## 20. 项目负责人确认结果

本文没有把技术问题留成无推荐答案的空白项。项目负责人已于 2026-08-17 单独确认：

- 默认模型为 `qwen3.8-max`，Provider 为 `qwen`。
- 官方 Base URL 固定为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，不允许 Web 或配置文件覆盖。
- `DASHSCOPE_API_KEY` 通过服务端进程环境或未纳入 Git 的本地 `.env` 文件提供；进程环境变量优先，Web 不管理 Provider 密钥。
- Web 当前和以后都不管理 Provider API Key，只显示“已配置/未配置”状态。

项目负责人于 2026-08-17 进一步确认以下会影响用户体验或外部成本的产品级选择：

1. 阶段 03 明确不展示思考摘要；这是为了避免把 `reasoning_content` 原始推理误当成安全摘要。
2. 聊天保持严格单轮，不保存历史；多轮、流式和取消全部进入阶段 04。
3. 最小页面只显示纯文本，不在本阶段增加 Markdown 或代码高亮。
4. 实现完成后，负责人已通过本地 `.env` 提供有效凭据并完成一次受控真实 API 调用及 Web 演示。

以上事项和 D03-01 ～ D03-17 均已确认，阶段 03 编码许可已经开放。

## 21. 当前结论

阶段 03 的代码、自动化测试、假 HTTP 演示和真实千问 Web 演示已经完成，当前状态为“已验收”。实现范围、接口、配置、错误和安全边界没有发生需要重新确认的产品级变化；模块拆分和生命周期落点等实现差异记录在同目录的 `completion-report.md`。阶段 04 的流式、多轮和取消设计单独记录在 `../04-web-streaming-multiturn-session/design.md`。

S03-01 ～ S03-13 均已完成，阶段 03 已标记为“已验收”。
