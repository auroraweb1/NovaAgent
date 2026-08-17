# 阶段 04 完成报告：Web 流式输出与多轮会话

> 状态：已实现；已测试；已验收
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-17
>
> 设计文档：[design.md](./design.md)
>
> 前置阶段：阶段 03 已完成并验收
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 报告目的

本文记录阶段 04 的实际实现、自动化测试、MockTransport 流式多会话演示、真实千问 Web 验收、覆盖率、设计差异和安全边界。

阶段 04 的设计已由项目负责人确认，代码、自动化质量门禁和真实千问流式多轮 Web 验收均已完成。项目负责人确认真实验收清单全部通过，本报告据此将阶段状态记录为“已验收”。

验收后的范围变更：项目负责人确认千问为唯一模型 Provider，不再接入豆包，也不建设模型多模态任务。本报告中的双 Provider 诊断结果仅记录阶段 04 当时的回归事实；遗留豆包配置和诊断输出由进度矩阵 MOD-06 跟踪清理。

## 2. 实现范围

### 2.1 领域事件与上下文

实现位置：`domain/events.py`、`domain/sessions.py`、`application/chat/context_window.py`、`application/protocol/driver.py`。

已实现：

- 新增 `ContextPreparedPayload`，不包含消息正文，只记录纳入消息数、裁剪消息数和 estimated input tokens。
- 事件顺序扩展为 `run_started → context_prepared → message_started → ... → terminal`。
- 协议驱动支持 `asyncio.CancelledError`，发布 `run_cancelled` 后重新传播取消并执行资源清理。
- 上下文按完整 user/assistant 轮次裁剪，默认保留最近 20 个成功轮次。
- 使用 UTF-8 字节数加消息开销的保守估算器，默认预算为 24,000 estimated tokens。
- 当前输入超过预算时发网前返回 `context_too_large`，不静默截断输入。

### 2.2 内存会话存储

实现位置：`domain/sessions.py`、`domain/ports.py`、`infrastructure/sessions/memory.py`。

已实现：

- 会话创建、列表、详情、清空和关闭。
- `revision` 从 0 开始，每次成功提交轮次或清空会话递增。
- `expected_revision` 防止陈旧浏览器覆盖新历史。
- registry lock 保护会话集合，per-session lock 保护会话状态和提交。
- 同一会话只允许一个活动 run，不排队；不同会话可以并发。
- 成功轮次以 user/assistant 两条消息原子提交。
- Provider 失败、取消、客户端断开和部分输出不写入正式历史。
- 服务进程重启后会话清空，不伪装为持久化能力。

### 2.3 千问流式 Adapter

实现位置：`infrastructure/models/qwen/adapter.py`。

已实现：

- 在固定官方 DashScope URL 上增加 `stream=true` 和 `stream_options.include_usage=true`。
- 解析供应商 SSE `data:` 行和 `[DONE]` 终止标记。
- content delta 映射为 `TextModelDelta`，usage 映射为 `UsageModelOutput`。
- role-only chunk、空 delta 和 keepalive 注释不会伪造文本。
- `reasoning_content`、tool calls、非法 JSON、非法 choices、非法 delta、非法 usage 和截断 EOF 稳定失败。
- 第一个可见 delta 前允许阶段 03 的有限重试；产生可见文本后禁止自动重试。
- 取消、失败和正常完成路径都关闭上游响应并释放 Provider 并发额度。
- 阶段 03 的非流式 `stream=false` 路径保持兼容。

### 2.4 多轮应用服务与 Run Registry

实现位置：`application/chat/multi_turn.py`、`bootstrap/container.py`。

已实现：

- `MultiTurnChatService` 组装历史、当前输入、上下文统计和 `ModelRequest`。
- 通过统一 `run_protocol()` 产生 AgentEvent，不建立第二套聊天事件流。
- `ActiveRunRegistry` 记录活动 run、取消任务并清理终止状态。
- 取消原因区分用户主动停止和客户端断开。
- 成功收到 `run_completed` 后才提交会话历史。
- 多轮服务与阶段 03 单轮服务共享同一个 Qwen Adapter 和 HTTP 客户端生命周期。

### 2.5 Web API、SSE 与页面

实现位置：`interfaces/web/app.py`、`interfaces/web/session_protocol.py`、`interfaces/web/static/`。

已实现：

- `POST /api/v1/sessions`、`GET /api/v1/sessions`、`GET /api/v1/sessions/{session_id}`。
- `DELETE /api/v1/sessions/{session_id}/messages`、`DELETE /api/v1/sessions/{session_id}`。
- `POST /api/v1/sessions/{session_id}/messages:stream`。
- `POST /api/v1/runs/{run_id}/cancel`。
- SSE 帧直接承载 AgentEvent JSON，使用有界队列和自然背压。
- 流建立前使用普通 JSON 错误信封，流建立后使用 `error → run_failed` 或 `run_cancelled` 事件。
- `Cache-Control: no-cache, no-transform` 和 `X-Accel-Buffering: no` 防止流被缓存或代理缓冲。
- 页面支持会话创建、切换、清空、关闭、流式显示、停止生成和 revision 展示。
- 页面继续使用纯文本 `textContent`，不引入 Markdown、CDN 或前端构建链。
- Web Token 只存在页面内存，Provider API Key 仍不出现在任何页面控件中。
- 阶段 03 `POST /api/v1/chat` 保持可用并通过回归测试。

## 3. 稳定错误

阶段 04 新增：

| 错误码 | HTTP | retryable | 触发条件 |
| --- | ---: | --- | --- |
| `session_not_found` | 404 | 否 | 会话不存在或已关闭 |
| `session_busy` | 409 | 是 | 同一会话已有活动 run |
| `session_revision_conflict` | 409 | 是 | 客户端 revision 已过期 |
| `session_limit_reached` | 409 | 否 | 进程会话数量达到上限 |
| `context_too_large` | 422 | 否 | 当前输入和固定消息超过预算 |
| `run_not_found` | 404 | 否 | 取消目标不存在或已结束 |
| `stream_protocol_invalid` | 502 | 否 | 供应商 SSE 格式或终止标记非法 |

## 4. 测试与验证证据

### 4.1 自动化结果

执行命令：

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache \
uv run pytest --cov=novaagent --cov-report=term-missing -q
```

结果：`180 passed`，项目总覆盖率 `94%`。

阶段 04 关键模块覆盖率：

| 模块 | 覆盖率 |
| --- | ---: |
| `application/chat/context_window.py` | 92% |
| `application/chat/multi_turn.py` | 96% |
| `application/protocol/driver.py` | 98% |
| `infrastructure/models/qwen/adapter.py` | 90% |
| `infrastructure/sessions/memory.py` | 97% |
| `interfaces/web/app.py` | 90% |
| `interfaces/web/session_protocol.py` | 100% |

覆盖的关键路径包括流式 delta、usage、`[DONE]`、reasoning 丢弃、非法供应商流、有限重试、缺少密钥、上下文裁剪、revision、会话隔离、成功原子提交、失败/取消不提交、SSE 帧、错误信封和阶段 03 全部回归。

### 4.2 质量门禁

以下命令全部通过：

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff format .
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff check .
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run mypy src tests
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run pytest --cov=novaagent --cov-report=term-missing -q
git diff --check
```

关键结果：

- Ruff：通过。
- Mypy：`Success: no issues found in 66 source files`。
- Pytest：`180 passed`。
- 总覆盖率：`94%`。
- Qwen streaming Adapter：`90%`。
- Git whitespace 检查：通过。

### 4.3 Doctor 回归

阶段 03 的 doctor 回归仍然正常。阶段 04 验收时配置仍识别千问和豆包；无真实密钥的自动化环境只报告预期 warning，不影响健康或诊断端点，也不会输出密钥。当前产品已收敛为仅千问，豆包相关诊断待 MOD-06 清理。

## 5. MockTransport 多会话演示

自动化集成测试完成以下闭环：

```text
创建 Session A
  → A 第一轮流式 delta
  → run_completed
  → 原子提交 user/assistant，revision=1
  → A 第二轮使用历史，revision=2
  → 读取 SessionSnapshot 验证两轮消息
```

测试确认：

- Web 收到 `agent_event` SSE 帧，而不是批量 JSON。
- Qwen 请求使用 `stream=true`、`stream_options.include_usage=true` 和 `enable_thinking=false`。
- 流式回答由多个 delta 拼接为最终 assistant Message。
- 真实历史只在成功终止后写入。
- revision 不匹配在发起流之前返回 HTTP 409。
- Session Store 使用内存实现，不同会话隔离。
- 阶段 03 `/api/v1/chat` 仍使用非流式请求，不受阶段 04 改动影响。

该演示没有访问互联网，也没有调用真实千问账号。

## 6. 设计与实现差异

| 项目 | 设计 | 实际实现 | 影响 |
| --- | --- | --- | --- |
| 前端流读取 | `fetch` + SSE | 原生 `fetch`、`ReadableStream` 和独立取消 API | 没有引入 EventSource 自动重连，避免重复提交 |
| Session Store Port | 扩展现有 Port | 保留阶段 02 兼容最小 Port，新增 `MultiTurnSessionStorePort` 承担 revision 事务 | 旧协议测试不破坏，多轮路径使用更严格接口 |
| token 估算 | 可替换估算 Port | 使用 UTF-8 字节保守估算 | 不依赖供应商 tokenizer，字段明确为 estimated |
| 浏览器自动化 | 可注入 fetch 或集成契约 | 本阶段使用 Web 集成契约和静态脚本边界，没有引入浏览器自动化依赖 | 保持项目构建简单，真实浏览器留作人工验收 |
| 流断开 | 检测断开并取消 | StreamingResponse 生成器取消生产任务，Run Registry 取消上游 | 不回放旧事件，断线后由用户重新发送 |

未改变 D04-01 ～ D04-24 的产品决策、阶段 03 API、密钥边界、Provider 白名单、纯文本输出和验收方式。

## 7. 安全与产品边界

- 没有将真实 `DASHSCOPE_API_KEY` 写入源码、TOML、测试、事件、页面或文档。
- Provider 密钥继续由本地 `.env` 或服务端运行时环境提供，Web 不管理密钥。
- SSE 只在服务端生成，浏览器不会直接请求 DashScope。
- 日志和事件不记录完整用户输入、完整回答、历史正文或供应商 SSE data。
- 页面使用 `textContent`，无 `innerHTML`、CDN、外部字体或 Markdown 渲染器。
- 非 loopback Web 仍强制 Token 鉴权，所有会话和取消 API 都使用同一鉴权依赖。
- 失败或取消的部分 assistant 内容不进入正式历史。
- 服务重启清空阶段 04 内存会话，页面明确提示这一点。

## 8. 真实 Web 验收记录

项目负责人确认使用本地 `.env` 配置完成真实千问流式多轮 Web 验收，并确认以下项目全部通过：

1. 创建两个独立 Web 会话，并分别完成至少两轮对话。
2. 千问回答在页面中逐段显示，非流式兼容 API 未受影响。
3. 同一会话第二轮能够使用上一轮上下文，不同会话之间没有上下文泄漏。
4. “停止生成”能够取消当前上游请求，取消的部分输出不进入正式历史。
5. 刷新、关闭页面或网络断开后，活动生成停止，已提交历史仍可读取。
6. 页面不显示 Provider API Key，也不显示原始思维链内容。

本次验收只记录验证结论和行为结果，不记录真实密钥、完整问题或完整回答。真实 Web 验收与自动化、MockTransport 证据共同构成阶段 04 的验收依据。

## 9. 当前结论

截至 2026-08-17：

- 设计：已确认。
- 实现：已完成。
- 自动化测试：已完成。
- MockTransport 流式多会话演示：已完成。
- 质量门禁：已完成。
- 真实千问流式多轮 Web 演示：项目负责人确认通过。
- 最终验收：已验收。

阶段结论：**阶段 04 Web 流式输出与多轮会话已完成并通过验收**。
