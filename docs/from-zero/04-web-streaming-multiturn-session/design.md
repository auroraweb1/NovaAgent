# 阶段 04 设计：Web 流式输出与多轮会话

> 状态：设计中；待项目负责人确认后开放编码
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-17
>
> 前置阶段：阶段 03 已完成并验收
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 文档目的

本文定义 NovaAgent 阶段 04“Web 流式输出与多轮会话”的实现边界、领域语义、应用服务、千问流式 Adapter、内存会话存储、SSE Web 协议、取消和断开处理、并发规则、上下文预算、安全边界、测试方案与验收门禁。

阶段 04 的目标不是建设完整 Agent，而是在阶段 02 的统一协议和阶段 03 的真实千问闭环之上，建立一条可以稳定演进的多轮流式聊天路径：

```text
浏览器会话
  → POST SSE 流式请求
  → 多轮聊天应用服务
  → 上下文选择与预算
  → QwenModelAdapter 流式响应
  → 统一 AgentEvent
  → Web SSE
  → 成功后原子提交会话历史
```

本文不直接授权编码。项目负责人确认 D04-01 ～ D04-24 后，阶段状态才能从“设计中”改为“待实现”。

## 2. 前置能力与约束

### 2.1 已有能力

阶段 02 已提供：

- 不依赖 Web 或供应商 SDK 的 `Message`、`ContentBlock`、`AgentEvent` 和核心 Port。
- `ModelPort.stream()` 异步输出协议。
- 成功、失败和取消的事件终止语义。
- `SessionStorePort` 的最小消息读取和追加接口。
- AgentEvent JSON 序列化与反序列化。

阶段 03 已提供：

- 固定 DashScope 官方 OpenAI-compatible 地址的 `QwenModelAdapter`。
- `qwen3.8-max` 默认模型和千问配置边界。
- 非流式 `SingleTurnChatService` 和 `POST /api/v1/chat`。
- local/token Web 鉴权、安全头、请求大小限制和统一错误信封。
- 纯文本 Web 页面和密钥配置状态。
- 本地 `.env` 密钥加载；Web 不管理 Provider API Key。

### 2.2 必须保持的产品边界

- 用户聊天入口仍然只有 Web 控制台。
- Provider 白名单仍然只有千问和豆包；阶段 04 仍只调用千问。
- 官方 Base URL 固定在 Adapter，Web、TOML 和 `.env` 均不能覆盖。
- `DASHSCOPE_API_KEY` 仍通过服务端进程环境或 Git 忽略的本地 `.env` 提供。
- Web 当前和后续均不录入、读取、修改、删除或持久化 Provider API Key。
- 原始思维链和 `reasoning_content` 继续被丢弃。
- 回答继续使用纯文本安全渲染，不引入 Markdown、代码高亮或 CDN。

## 3. 阶段目标

阶段 04 必须完成：

1. 将千问流式 HTTP 响应逐段映射为统一 `AgentEvent`。
2. 使用 Web SSE 将同一事件流实时发送给浏览器。
3. 创建、列出、选择、查看、清空和关闭内存会话。
4. 将已成功完成的 user/assistant 对话轮次用于后续模型请求。
5. 保证同一会话消息顺序确定，不同会话并发且互不污染。
6. 支持用户主动停止生成和浏览器断开后的后端取消。
7. 建立上下文轮次限制、保守 token 估算接口和可测试裁剪规则。
8. 保留阶段 03 非流式 API 的兼容行为和回归测试。
9. 使用 MockTransport 完成无网络、确定性的流式与多会话测试。
10. 自动化通过后，使用真实千问执行一次受控流式 Web 验收。

## 4. 非目标

阶段 04 明确不做：

- 不实现工具定义、工具调用、工具执行或 Agent 决策循环；进入阶段 05。
- 不实现 SQLite、会话重启恢复、长期记忆、自动摘要或历史搜索；进入阶段 10。
- 不实现豆包 Adapter；进入阶段 14。
- 不实现图片、音频、文件或其他多模态输入；进入阶段 14。
- 不实现 Markdown、代码高亮、工具卡片、推理卡片或完整控制台导航；进入阶段 07。
- 不展示、保存、记录或转发原始思维链。
- 不实现跨进程、跨实例或分布式会话锁。
- 不实现断线后基于 `Last-Event-ID` 的事件回放。
- 不实现聊天分支、消息编辑、重新生成、分享、导出或搜索。
- 不允许浏览器选择 Provider、模型、温度、最大 token 或供应商参数。
- 不新增终端聊天、桌面端或第三方消息通道。
- 不在失败或取消后把不完整 assistant 文本写入正式会话历史。

## 5. 使用场景

### 5.1 创建会话并连续对话

用户打开 Web 页面，创建会话并发送第一条消息。回答逐段显示；完成后 user/assistant 两条消息作为一个成功轮次提交。用户发送第二条消息时，模型请求包含上一轮历史和当前消息。

### 5.2 两个会话互不污染

用户创建两个会话并分别讨论不同主题。每个模型请求只包含目标会话的已提交历史；一个会话的回答、取消、清空或错误不改变另一个会话。

### 5.3 用户停止生成

用户在回答过程中点击“停止生成”。浏览器请求取消当前 run，后端取消千问流式读取、释放连接和并发额度，并尽可能发送 `run_cancelled`。本轮 user 和部分 assistant 输出不提交到正式历史。

### 5.4 浏览器断开

浏览器关闭页面、切换会话导致流被主动中止或网络连接断开时，后端检测断开并取消对应 run。阶段 04 不在后台继续生成，也不保存断开后的回答。

### 5.5 上下文超限

会话历史超过轮次或输入预算时，系统从最旧的完整成功轮次开始裁剪，保留最近历史和当前用户消息。若当前消息本身超过预算，则在发网前拒绝，不静默截断用户输入。

### 5.6 供应商半途失败

千问已经输出部分文本后发生超时、断连或非法响应。Web 收到此前文本和稳定失败事件，但该轮不进入正式历史。系统不得自动重试已产生可见文本的请求，以免重复计费和重复输出。

## 6. 总体架构

推荐模块边界：

```text
src/novaagent/
├── application/
│   ├── chat/
│   │   ├── single_turn.py
│   │   ├── multi_turn.py
│   │   └── context_window.py
│   └── protocol/
│       └── driver.py
├── domain/
│   ├── events.py
│   ├── messages.py
│   ├── ports.py
│   └── sessions.py
├── infrastructure/
│   ├── models/qwen/adapter.py
│   └── sessions/memory.py
├── interfaces/web/
│   ├── app.py
│   ├── chat_protocol.py
│   ├── session_protocol.py
│   ├── sse.py
│   └── static/
└── bootstrap/container.py
```

依赖方向保持：

```text
Web Adapter → Application → Domain Ports ← Infrastructure Adapters
```

Domain 和 Application 不导入 FastAPI、Starlette、HTTPX 或 DashScope 类型。SSE 编码只存在于 Web Adapter；供应商 SSE 解析只存在于 Qwen Adapter。

## 7. 核心领域模型

### 7.1 会话标识和生命周期

会话 ID 使用现有标识符规则生成，例如：

```text
session-<uuid>
```

阶段 04 的会话状态只存在于当前进程内：

```text
created → active → cleared（仍 active）→ deleted
```

- `created`：会话存在，历史为空，revision 为 0。
- `active`：会话可读取和发送消息。
- `cleared`：历史被清空，revision 增加，会话本身仍存在。
- `deleted`：会话从内存存储移除，后续访问返回 `session_not_found`。

进程重启后所有阶段 04 会话丢失，这是明确的产品行为，不伪装为持久化故障。Web 页面必须提示“当前会话仅保存在本次服务运行期间”。

### 7.2 SessionSnapshot

推荐领域对象：

```text
SessionSnapshot
  session_id: str
  revision: int
  title: str
  messages: tuple[Message, ...]
  created_at: datetime
  updated_at: datetime
  active_run_id: str | None
```

约束：

- `revision` 从 0 开始，每次成功提交轮次、清空会话时加 1。
- `title` 由服务端根据第一条成功 user 消息生成，最大 40 个 Unicode 字符；空会话显示“新会话”。
- `messages` 只包含成功提交的完整 user/assistant 轮次，因此数量始终为偶数。
- `active_run_id` 是瞬时状态，用于页面和冲突提示，不持久化。
- 列表 API 返回不含完整消息的摘要对象；详情 API 才返回消息。

### 7.3 成功轮次的原子提交

一次多轮请求使用以下事务语义：

1. 验证会话存在、revision 匹配且没有活动 run。
2. 创建当前 user Message，但暂不写入正式历史。
3. 使用已提交历史和当前 user Message 构造模型请求。
4. 将流式 AgentEvent 发送给 Web。
5. 只有收到完整 `run_completed` 后，才把 user Message 和最终 assistant Message 一次性追加。
6. 成功提交后 revision 加 1。
7. 失败、取消或客户端断开时，两条消息都不提交。

该规则避免未完成 user 消息在下一轮上下文中重复出现，也避免部分 assistant 文本污染历史。页面可以在当前连接中保留失败或取消的临时显示，但刷新详情后只展示已提交历史。

## 8. Session Store Port 与内存实现

### 8.1 Port 扩展

阶段 02 的最小 `SessionStorePort` 需要在阶段 04 扩展，而不是由 Web 直接操作字典。推荐能力：

```text
create_session() -> SessionSnapshot
list_sessions() -> tuple[SessionSummary, ...]
get_session(session_id) -> SessionSnapshot
commit_turn(session_id, expected_revision, user, assistant) -> SessionSnapshot
clear_session(session_id, expected_revision) -> SessionSnapshot
delete_session(session_id, expected_revision) -> None
set_active_run(session_id, expected_revision, run_id) -> SessionSnapshot
clear_active_run(session_id, run_id) -> None
```

现有 `get_messages()` 和 `append_messages()` 不再作为应用服务的主要事务入口；可保留为兼容的低层协议方法，但正式多轮路径必须使用带 revision 的原子操作。

### 8.2 乐观并发版本

阶段 02 推迟了是否加入乐观并发版本的决定。阶段 04 推荐正式采用 `revision`：

- 浏览器发送消息时携带当前 `expected_revision`。
- revision 不匹配返回 `session_revision_conflict`，HTTP 409。
- 页面收到冲突后重新拉取会话详情，不自动覆盖其他标签页提交的消息。
- revision 保护陈旧客户端；单会话锁保护同一进程中的运行时竞态，两者职责不同。

### 8.3 锁粒度

内存实现使用：

- 一个短持有的 registry lock，保护会话字典创建、列出和删除。
- 每个会话一个独立 `asyncio.Lock`，保护 revision、活动 run 和消息提交。
- 不在供应商网络请求全程持有 registry lock。
- 同一会话同一时间只允许一个活动 run；不同会话可以并发。
- Provider 级并发仍受 `max_concurrency` 限制。

第二个针对忙碌会话的发送请求立即返回 `session_busy`，HTTP 409，不排队等待，以免用户误以为多个输入已经按未知顺序入队。

### 8.4 排序和容量

- 会话列表按 `updated_at` 降序，再按 `session_id` 保证确定性。
- 阶段 04 默认每进程最多 100 个会话。
- 达到上限时创建会话返回 `session_limit_reached`，HTTP 409。
- 不自动删除最旧会话，避免无提示数据消失。
- 单会话正式历史默认最多保留 100 个成功轮次；达到上限时仍可继续发送，但模型上下文按预算裁剪，历史对象不在阶段 04 自动删除。

会话和历史硬容量未来可进入配置；阶段 04 先使用模块常量并通过测试锁定，避免为早期能力扩大配置面。

## 9. 上下文组装与预算

### 9.1 消息顺序

模型请求顺序固定为：

```text
服务端系统消息（阶段 04 默认空）
→ 被选中的完整历史轮次，按时间正序
→ 当前 user Message
```

阶段 04 不配置自定义系统提示词；该能力留到阶段 08。应用服务保留只读 `system_messages` 注入点，默认 `()`，测试可以验证顺序。

### 9.2 轮次限制

默认最多向模型发送最近 20 个成功轮次，不包括当前 user Message。裁剪只能删除最旧的完整 user/assistant 对，不能拆开轮次，也不能重排消息。

### 9.3 TokenBudgetPort

阶段 04 引入供应商无关的估算接口：

```text
estimate(messages) -> int
select(system_messages, turns, current_user, budget) -> ContextSelection
```

阶段 04 不引入千问 tokenizer 依赖。默认估算器使用 UTF-8 字节数加每条消息固定开销，结果明确命名为“estimated tokens”，不宣称等于供应商账单 token。该估算对中英文文本偏保守，可确定性测试；阶段 10 可替换为更精确 tokenizer 和摘要策略。

默认输入预算为 24,000 estimated tokens。选择算法：

1. 始终保留服务端系统消息和当前 user Message。
2. 从最新成功轮次向前加入完整轮次。
3. 达到 20 轮或 24,000 预算后停止。
4. 输出按原始时间顺序恢复。
5. 若系统消息和当前 user Message已经超过预算，返回 `context_too_large`，HTTP 422，零供应商请求。

### 9.4 可观测裁剪事件

扩展统一 AgentEvent，新增可选 `context_prepared` payload：

```json
{
  "type": "context_prepared",
  "included_messages": 11,
  "dropped_messages": 6,
  "estimated_input_tokens": 8200
}
```

事件顺序为：

```text
run_started
→ context_prepared
→ message_started
→ text_delta*
→ message_completed
→ run_completed
```

`context_prepared` 不包含消息正文。即使没有裁剪也发送，方便测试和页面稳定显示上下文摘要。阶段 02 的 JSON 版本保持 `1`；新增 payload 类型属于向后兼容扩展，旧消费者若不支持必须显式拒绝，阶段 04 Web 使用更新后的 Schema。

## 10. 千问流式 Adapter

### 10.1 请求

阶段 04 在现有固定地址上增加流式请求：

```text
POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
Authorization: Bearer <DASHSCOPE_API_KEY>
Content-Type: application/json
```

请求关键字段：

```json
{
  "model": "qwen3.8-max",
  "messages": [],
  "stream": true,
  "stream_options": {"include_usage": true},
  "enable_thinking": false,
  "temperature": 0.7,
  "max_tokens": 2048
}
```

阶段 03 的非流式路径仍发送 `stream=false`；阶段 04 多轮路径发送 `stream=true`。两条路径共享请求校验、固定 URL、鉴权、错误映射、超时和并发额度，不复制两套 Adapter。

### 10.2 供应商 SSE 解析

Adapter 使用 HTTPX 流式响应逐行解析：

```text
data: {JSON}

data: [DONE]

```

规则：

- 忽略空行和标准 SSE 注释行。
- 每个 `choices[0].delta.content` 非空字符串映射为 `TextModelDelta`。
- role-only 空 delta 不产生文本事件。
- 最终 usage 映射为 `UsageModelOutput`；usage 允许缺失。
- `reasoning_content`、原始思维链和未知隐藏推理字段全部丢弃。
- 出现 tool calls、非文本 content、非法 JSON、非法 choices 或非法 usage 时返回 `provider_response_invalid`。
- 正常流必须以 `[DONE]` 结束；没有终止标记的 EOF 视为截断失败。
- Adapter 不把供应商 SSE 字符串或 HTTPX 对象泄漏到 Domain/Application。

### 10.3 流式重试

- 在产生第一个可见文本 delta 之前，可以沿用阶段 03 的有限重试规则。
- 一旦产生任何文本 delta，不再自动重试连接、超时、429 或 5xx。
- 读取超时不自动重试。
- 不允许把第二次尝试的文本接在第一次部分文本后面。
- 重试次数仍由 `max_retries` 控制，默认最多一次。

### 10.4 取消和资源释放

- Adapter 的响应流必须使用异步上下文管理器关闭。
- `asyncio.CancelledError` 必须原样传播，不转换为 `dependency_unavailable`。
- 取消时关闭上游响应、释放 semaphore 和 HTTP 连接。
- 正常、失败、取消和解析异常路径全部通过 `finally` 释放资源。

## 11. 应用服务与事件驱动

### 11.1 MultiTurnChatService

推荐入口：

```text
stream_chat(session_id, expected_revision, text, sink) -> Async completion
```

职责：

1. 校验消息非空、字符上限、会话状态和 revision。
2. 为会话声明一个活动 run。
3. 选择历史和上下文预算。
4. 调用统一协议驱动产生 AgentEvent。
5. 将事件发布到 Web SSE sink。
6. 成功时原子提交当前 user 和最终 assistant Message。
7. 失败或取消时不提交本轮。
8. 在所有终止路径清理活动 run 和 Run Registry。

它不负责 HTTP、SSE 字符串、浏览器断开检查或 HTTPX 解析。

### 11.2 协议驱动取消扩展

现有 `run_protocol()` 必须增加显式取消处理：

- 捕获模型迭代期间的 `asyncio.CancelledError`。
- 尝试发布 `RunCancelledPayload(reason="user_requested" | "client_disconnected")`。
- 完成事件序列校验后重新传播一个应用层取消结果，而不是转成通用依赖错误。
- 调用模型异步迭代器的 `aclose()`，确保 Adapter 关闭网络流。
- 如果 SSE sink 已因客户端断开不可写，仍必须完成本地清理；不能因为无法发送取消事件而跳过资源释放。

### 11.3 有界事件队列和背压

Web Adapter 与应用服务之间使用容量 64 的有界异步队列：

- 应用服务向队列发布 AgentEvent。
- StreamingResponse 从队列读取并编码为 SSE。
- 客户端读取缓慢时，队列满会反向阻塞模型读取，避免无限内存增长。
- 终止事件后关闭队列。
- 客户端断开时取消生产任务并清空引用。

不得为每个 delta 创建无上限后台任务。

## 12. Run Registry 与取消

### 12.1 Run Registry

进程内 registry 记录：

```text
run_id → session_id, asyncio.Task, cancellation_reason
```

规则：

- run 在发送 `run_started` 前注册。
- 完成、失败或取消后在 `finally` 中移除。
- registry 只保存活动 run，不保存历史正文或终止结果。
- 同一 run 的重复取消是幂等信号，不重复发布终止事件。

### 12.2 主动取消 API

```text
POST /api/v1/runs/{run_id}/cancel
```

成功：

```json
{
  "protocol_version": "1",
  "run_id": "run-...",
  "status": "cancellation_requested"
}
```

状态码 `202`。run 不存在或已经结束时返回 `run_not_found`、HTTP 404。完成与取消竞态中，如果 Web 已经收到 `run_completed`，页面忽略随后取消请求的 404。

### 12.3 浏览器断开

StreamingResponse 生成器周期性检查请求是否断开；断开或生成器收到取消时：

1. 以 `client_disconnected` 原因取消生产任务。
2. 等待应用服务和 Adapter 完成清理。
3. 不尝试向已关闭连接继续发送事件。
4. 不提交本轮历史。

阶段 04 使用 `fetch` 和 `AbortController`，不使用浏览器 `EventSource` 自动重连，因此不会在断开后无意重复提交同一条用户消息。

## 13. Web API

所有 `/api/v1/*` 会话、聊天、取消和诊断接口继续使用阶段 03 的 local/token 鉴权规则。页面与静态资源仍可公开加载，但没有 Token 时不能调用受保护 API。

### 13.1 创建会话

```text
POST /api/v1/sessions
```

请求体为空或 `{}`，返回 `201`：

```json
{
  "protocol_version": "1",
  "session": {
    "session_id": "session-...",
    "revision": 0,
    "title": "新会话",
    "message_count": 0,
    "active_run_id": null,
    "created_at": "2026-08-17T00:00:00Z",
    "updated_at": "2026-08-17T00:00:00Z"
  }
}
```

### 13.2 会话列表

```text
GET /api/v1/sessions
```

返回按最近更新排序的摘要，不返回消息正文。

### 13.3 会话详情

```text
GET /api/v1/sessions/{session_id}
```

返回会话摘要和完整已提交 Message 列表。未知会话返回 `session_not_found`、HTTP 404。

### 13.4 流式发送

```text
POST /api/v1/sessions/{session_id}/messages:stream
Content-Type: application/json
Accept: text/event-stream
```

请求：

```json
{
  "message": "继续解释上一轮内容",
  "expected_revision": 1
}
```

建立流之前可以确定的输入、鉴权、会话、revision 和 busy 错误使用普通 JSON 错误信封及对应 HTTP 状态。建立流后发生的模型错误使用 AgentEvent 失败序列表示，HTTP 状态保持 200。

响应头至少包含：

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
X-Accel-Buffering: no
X-Content-Type-Options: nosniff
```

### 13.5 SSE 帧

每个领域事件编码为：

```text
event: agent_event
id: 0
data: {AgentEvent JSON}

```

- `id` 等于 AgentEvent 的 `sequence`，只用于当前连接诊断，不承诺重放。
- `data` 使用阶段 02 的 AgentEvent JSON Schema，不创建第二套 delta/Error 格式。
- 每 15 秒无语义事件时可以发送 `: keepalive` 注释；keepalive 不进入领域事件序列。
- 终端 payload 必须是 `run_completed`、`run_failed` 或 `run_cancelled` 之一。
- 终端事件后服务器关闭当前 SSE 响应。

### 13.6 清空会话

```text
DELETE /api/v1/sessions/{session_id}/messages?expected_revision=3
```

成功返回清空后的会话详情。会话有活动 run 时返回 `session_busy`；revision 不匹配返回 `session_revision_conflict`。

### 13.7 关闭会话

```text
DELETE /api/v1/sessions/{session_id}?expected_revision=3
```

成功返回 `204`。会话有活动 run 时不隐式取消，返回 `session_busy`；用户需先停止生成，再关闭会话。

### 13.8 阶段 03 API 兼容

```text
POST /api/v1/chat
```

阶段 04 保留该非流式、无会话接口和既有 Schema，作为兼容与回归路径。阶段 04 Web 页面改用新会话流式 API。是否在阶段 07 移除或标记废弃，需要单独设计，阶段 04 不破坏它。

## 14. Web 页面设计

页面继续使用仓库内静态 HTML、CSS 和原生 JavaScript，不增加 Node.js 构建链或第三方前端依赖。

最小布局：

```text
┌─────────────────┬────────────────────────────────────┐
│ 新建会话        │ 当前会话标题 / 内存会话提示        │
│ 会话 A          │                                    │
│ 会话 B          │ user / assistant 消息              │
│                 │ 流式 assistant 临时消息            │
│ 清空 / 关闭     │                                    │
│                 │ 输入框  [发送] [停止生成]           │
└─────────────────┴────────────────────────────────────┘
```

行为：

- 首次打开页面自动创建一个会话；已有会话时默认选择最近更新的会话。
- 会话列表显示标题、更新时间和活动状态，不显示消息预览中的敏感正文。
- 发送后立即以临时状态显示 user 消息，并逐段追加 assistant 文本。
- 收到 `run_completed` 后重新获取会话详情和 revision。
- 收到失败或取消事件时保留当前页面中的临时轮次并标记“未保存”；刷新后不再出现。
- “停止生成”只在当前会话存在活动 run 时启用。
- 切换会话时如果当前会话正在生成，默认不自动取消；页面可以让该流在后台继续接收，但同一页面最多维护 4 个活动流。超过限制时提示用户先停止已有生成。
- 清空和关闭操作必须二次确认；阶段 04 的确认只在 Web 页面完成。
- 所有用户和模型文本通过 `textContent` 渲染，禁止 `innerHTML`。
- Web Token 仍只保存在当前页面内存中，不进入 URL、Cookie 或本地存储。
- Provider API Key 不出现在任何输入控件中。

为控制复杂度，阶段 04 不实现浏览器刷新后的活动流恢复；刷新会导致旧连接断开并取消对应 run，然后重新加载已提交历史。

## 15. 稳定错误

阶段 04 新增：

| 错误码 | HTTP | retryable | 说明 |
| --- | ---: | --- | --- |
| `session_not_found` | 404 | 否 | 会话不存在或已关闭 |
| `session_busy` | 409 | 是 | 同一会话已有活动 run |
| `session_revision_conflict` | 409 | 是 | 客户端 revision 已过期 |
| `session_limit_reached` | 409 | 否 | 当前进程达到会话容量 |
| `context_too_large` | 422 | 否 | 系统消息和当前输入已经超过预算 |
| `run_not_found` | 404 | 否 | 取消目标不存在或已终止 |
| `stream_protocol_invalid` | 502 | 否 | 供应商流式响应格式或终止语义非法 |

流建立前错误使用普通 JSON 错误信封；流建立后错误按以下事件序列结束：

```text
error → run_failed
```

取消按以下事件结束：

```text
run_cancelled
```

`asyncio.CancelledError` 不能进入全局 500 handler，也不能记录为未处理异常。

## 16. 安全、隐私与日志

- 不记录完整 user 消息、assistant 消息、历史上下文或供应商 SSE data。
- 可记录 request ID、run ID、session ID、Provider、模型、耗时、事件数、裁剪消息数、usage 和稳定错误码。
- session ID、run ID 和 request ID 不视为凭据，但日志中不得与完整正文组合。
- API Key 只存在服务端运行时环境和 Authorization 请求头构造边界；不得进入事件、会话或 SSE。
- 错误正文不透传 DashScope 原始响应，不回显请求头。
- 页面 CSP 保持 `connect-src 'self'`，不允许浏览器直接请求 DashScope。
- 非 loopback 监听仍强制 token 鉴权。
- 所有会话 API 都必须通过与聊天 API 相同的鉴权依赖。
- 清空和关闭仅影响当前进程内目标会话，不能接受路径、文件名或工作空间位置。
- SSE 禁止缓存和反向代理缓冲，避免延迟和中间层持久化流内容。

## 17. 配置

阶段 04 继续使用现有千问配置：

```toml
[providers.qwen]
model = "qwen3.8-max"
temperature = 0.7
max_output_tokens = 2048
timeout_seconds = 60
max_retries = 1
max_concurrency = 4
```

以下阶段 04 策略先作为应用常量并被测试锁定：

```text
MAX_SESSIONS = 100
MAX_HISTORY_TURNS = 100
MODEL_CONTEXT_TURNS = 20
MODEL_CONTEXT_ESTIMATED_TOKEN_BUDGET = 24000
SSE_QUEUE_CAPACITY = 64
SSE_KEEPALIVE_SECONDS = 15
MAX_PAGE_ACTIVE_STREAMS = 4
```

这些值出现真实运行调整需求后再进入 TOML；阶段 04 不通过 Web 修改配置。`.env` 继续只允许密钥相关键，不加入会话或流式策略。

## 18. 测试策略

### 18.1 领域和协议测试

- `context_prepared` payload 构造、序列化、反序列化和非法字段。
- 成功、失败和取消事件顺序。
- `run_protocol()` 取消时只产生一个终端事件。
- sink 不可写时仍关闭模型迭代器和清理资源。
- 新事件对既有阶段 02 事件回归无破坏。

### 18.2 上下文预算测试

- 空历史、单轮和多轮消息顺序。
- 最多 20 个完整轮次。
- UTF-8 估算确定性。
- 从最旧完整轮次开始裁剪。
- 当前输入超过预算时零模型调用。
- 不拆分 user/assistant 对。
- 裁剪统计不包含正文。

### 18.3 内存会话测试

- 创建、列表排序、详情、标题生成、清空和删除。
- revision 从 0 开始并单调增加。
- 错误 revision 不修改状态。
- 原子提交 user/assistant 对。
- 失败和取消不提交。
- 同会话 busy 冲突。
- 不同会话并发和隔离。
- 会话容量边界。

### 18.4 Qwen Adapter 流式测试

- 固定 URL、Authorization、`stream=true`、`include_usage` 和 `enable_thinking=false`。
- 多个 content delta 的顺序和最终拼接。
- role-only chunk、空 chunk 和 SSE 注释。
- usage 存在和缺失。
- reasoning 字段丢弃。
- `[DONE]` 终止。
- 非法 JSON、choices、delta、tool calls、usage 和无 `[DONE]` EOF。
- 首个 delta 前有限重试。
- 首个 delta 后错误不重试。
- 取消关闭响应并释放 semaphore。
- 两个不同请求并发时不串流。

### 18.5 应用服务测试

- 历史 + 当前消息正确形成 ModelRequest。
- AgentEvent 实时透传，不等最终回答后批量发送。
- 成功后提交并增加 revision。
- Provider 失败、客户端断开和主动取消不提交。
- 活动 run 在所有终止路径被清理。
- 一个会话的取消不影响另一个会话。

### 18.6 Web 集成测试

- 创建、列表、详情、清空和关闭 API。
- local/token 鉴权。
- POST SSE 请求和 AgentEvent 帧格式。
- JSON 错误与流内错误的边界。
- keepalive 不进入领域事件。
- 停止生成 API。
- 客户端断开取消生产任务。
- no-cache、no-buffer、安全头和 request ID。
- revision conflict、session busy、not found 和容量错误。
- 阶段 03 `/api/v1/chat` 全部回归。

### 18.7 前端行为测试

项目当前没有浏览器自动化框架，阶段 04 不为一个静态页面引入大型端到端依赖。通过可注入 fetch 的 JavaScript 边界或 Web 集成契约覆盖主要协议，人工验收覆盖真实浏览器交互：

- 创建和切换会话。
- 流式文字逐段出现。
- 停止按钮状态。
- 失败/取消临时轮次标记。
- 页面刷新导致活动 run 取消。
- 纯文本渲染和密钥不可见。

### 18.8 覆盖率门禁

- 项目总覆盖率不低于 80%。
- `multi_turn.py`、`context_window.py`、内存 Session Store 和 Qwen Adapter 各不低于 90%。
- Web 会话/SSE 协议模块不低于 90%。
- Ruff、Mypy、Pytest、`doctor`、`git diff --check` 和 GitHub Actions 全部通过。

## 19. 最小演示与验收

### 19.1 MockTransport 无网络演示

自动化演示必须完成：

```text
创建 Session A 和 Session B
→ A 第一轮流式输出多个 delta 并提交
→ A 第二轮请求包含 A 第一轮历史
→ B 请求不包含 A 的任何消息
→ 取消 A 的活动 run
→ B 继续完成并提交
→ 读取两个 SessionSnapshot 验证隔离和 revision
```

必须断言事件顺序、逐段输出、最终文本、usage、revision、历史内容、取消清理和上游请求次数。

### 19.2 真实千问 Web 演示

在自动化通过后，由项目负责人使用本地 `.env` 完成：

1. `doctor` 确认千问密钥已配置，但不显示值。
2. 创建两个 Web 会话。
3. 在 Session A 连续发送两轮，第二轮明确依赖第一轮事实，确认多轮上下文生效。
4. 在 Session B 提问，确认没有 Session A 的上下文。
5. 确认真实回答逐段显示而不是结束后一次出现。
6. 对一个较长回答点击停止，确认很快停止且页面标记本轮未保存。
7. 停止或断开后再次发送，确认会话可继续使用。
8. 确认 Provider、`qwen3.8-max`、usage、耗时和上下文统计显示合理。
9. 确认页面不显示 API Key、原始思维链或 `reasoning_content`。

完成报告只记录检查结果、usage 是否存在和取消是否生效，不记录真实密钥或完整问答正文。

### 19.3 阶段完成条件

阶段 04 只有同时满足以下条件才能标记“已完成/已验收”：

1. 设计确认。
2. 代码实现完成。
3. 自动化测试和覆盖率通过。
4. Ruff 和 Mypy 通过。
5. MockTransport 多会话流式演示通过。
6. 取消、断开和资源释放证据通过。
7. 真实千问 Web 流式多轮演示通过，或负责人明确批准组合证据替代。
8. 完成报告、总体路线和进度矩阵同步。

## 20. 实施顺序

设计确认后的推荐编码顺序：

1. 扩展领域 Session 对象、稳定错误和 `context_prepared` 事件。
2. 实现上下文估算与选择策略。
3. 实现带 revision 和单会话锁的内存 Session Store。
4. 扩展协议驱动的取消语义。
5. 扩展 Qwen Adapter 解析供应商 SSE。
6. 实现 `MultiTurnChatService` 和 Run Registry。
7. 实现会话 REST API、POST SSE 和取消 API。
8. 更新静态 Web 页面支持会话、流式和停止。
9. 添加单元、契约和集成测试。
10. 更新 README 和阶段 04 完成报告。
11. 运行完整质量门禁。
12. 执行真实千问 Web 验收。

每一步先完成最窄测试再进入下一步，最终运行完整回归。阶段 03 非流式 API 在全过程保持可用。

## 21. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 流式半途失败污染历史 | 只在 `run_completed` 后原子提交完整轮次 |
| 自动重试产生重复文本或费用 | 首个可见 delta 后禁止重试 |
| 慢客户端造成内存增长 | 有界事件队列和自然背压 |
| 断开后继续计费 | 检测断开并取消生产任务和上游响应 |
| 同会话并发导致历史乱序 | 单会话活动 run + per-session lock + revision |
| 多标签页覆盖新消息 | `expected_revision` 冲突并要求重新加载 |
| 不同会话串上下文 | 按 session ID 获取不可变快照并做隔离测试 |
| 上下文过大导致上游拒绝 | 完整轮次裁剪、保守估算、当前输入超限前置拒绝 |
| token 估算被误认为账单值 | 字段明确标记 estimated，usage 仍使用供应商结果 |
| 取消竞态产生双终止事件 | EventSequenceValidator + 幂等取消 + finally 清理 |
| SSE 错误无法修改 HTTP 状态 | 流前错误用 JSON；流后错误用统一失败事件 |
| 代理缓冲破坏实时性 | `no-cache`、`no-transform`、`X-Accel-Buffering: no` |
| 页面注入 | 纯文本 `textContent`、CSP、无 CDN、无 innerHTML |
| 内存会话被误认为持久化 | 页面明确提示，阶段 10 再实现恢复 |
| 阶段 04 范围膨胀 | 明确排除工具、持久化、Markdown、多模态和豆包 |

## 22. 推荐决策

本文对待确定问题给出以下推荐答案，等待项目负责人整体确认：

| 编号 | 决策 | 推荐答案 | 状态 |
| --- | --- | --- | --- |
| D04-01 | 浏览器流式协议 | 使用 POST + `fetch` 读取 SSE，不使用 WebSocket 或 EventSource | 推荐，待确认 |
| D04-02 | SSE 数据格式 | 每帧只承载阶段 02 AgentEvent JSON，不建立第二套流事件 | 推荐，待确认 |
| D04-03 | 阶段 03 API | 保留 `POST /api/v1/chat` 非流式兼容路径 | 推荐，待确认 |
| D04-04 | 会话存储 | 阶段 04 只使用进程内内存存储，重启清空 | 推荐，待确认 |
| D04-05 | 持久化 | SQLite、恢复和长期历史进入阶段 10 | 推荐，待确认 |
| D04-06 | 会话并发 | 同会话只允许一个活动 run，不排队；不同会话可并发 | 推荐，待确认 |
| D04-07 | 陈旧客户端 | 使用 `expected_revision` 和 HTTP 409 防止覆盖 | 推荐，待确认 |
| D04-08 | 历史提交 | 只在成功完成后原子提交 user/assistant 对 | 推荐，待确认 |
| D04-09 | 失败和取消部分文本 | 当前页面临时显示但不进入正式历史 | 推荐，待确认 |
| D04-10 | 用户主动取消 | `POST /api/v1/runs/{run_id}/cancel`，返回 202 | 推荐，待确认 |
| D04-11 | 客户端断开 | 取消上游请求，不在后台继续生成 | 推荐，待确认 |
| D04-12 | 流式重试 | 首个文本 delta 前有限重试，之后禁止自动重试 | 推荐，待确认 |
| D04-13 | 上下文轮次 | 默认最近 20 个完整成功轮次 | 推荐，待确认 |
| D04-14 | 上下文预算 | 默认 24,000 estimated tokens，使用可替换估算 Port | 推荐，待确认 |
| D04-15 | 上下文裁剪 | 从最旧完整轮次开始，当前输入绝不静默截断 | 推荐，待确认 |
| D04-16 | 系统提示词 | 阶段 04 默认无系统消息，只预留服务端注入点 | 推荐，待确认 |
| D04-17 | 裁剪可观测性 | 新增不含正文的 `context_prepared` AgentEvent | 推荐，待确认 |
| D04-18 | 会话容量 | 每进程最多 100 个，不自动淘汰 | 推荐，待确认 |
| D04-19 | SSE 背压 | 每连接容量 64 的有界队列 | 推荐，待确认 |
| D04-20 | 断线恢复 | 阶段 04 不回放事件；断线即取消，用户重试 | 推荐，待确认 |
| D04-21 | 前端实现 | 继续原生 HTML/CSS/JavaScript，不增加构建链 | 推荐，待确认 |
| D04-22 | 输出渲染 | 继续纯文本，Markdown 留到阶段 07 | 推荐，待确认 |
| D04-23 | 密钥管理 | 继续使用 `.env`/服务端环境，Web 永不管理 Provider 密钥 | 推荐，待确认 |
| D04-24 | 阶段验收 | 自动化 + MockTransport + 真实千问双会话流式演示 | 推荐，待确认 |

## 23. 当前结论

阶段 03 已通过真实 Web 验收，阶段 04 的前置条件已经满足。本文已经为 SSE、会话状态、revision、原子提交、取消、断开、上下文预算、错误边界、安全规则和验收方式给出推荐答案，没有把架构问题留成无建议的空白项。

当前状态仍是“设计中”。项目负责人确认 D04-01 ～ D04-24 后，应执行：

1. 将本文状态改为“设计已确认；待实现”。
2. 将总体路线和进度矩阵中的阶段 04 设计状态改为“已确认”。
3. 按第 20 节顺序开始代码与测试。
4. 实现完成前不创建 `completion-report.md`，避免提前形成完成错觉。
