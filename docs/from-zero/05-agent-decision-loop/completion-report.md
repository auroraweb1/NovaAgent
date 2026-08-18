# 阶段 05 完成报告：Agent 决策循环

> 状态：已验收
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-18
>
> 设计文档：[design.md](./design.md)
>
> 前置阶段：阶段 04 已完成并验收
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 报告目的

本文记录阶段 05 的实现范围、自动化验证、MockTransport Web 闭环、质量门禁、真实千问协议复验和负责人验收结论。首次真实千问 Web echo 发现的协议兼容问题已经修复；项目负责人于 2026-08-18 确认修复后的浏览器 echo 调用成功，阶段状态更新为“已验收”。

## 2. 实现范围

### 2.1 Provider 范围收敛

实现位置：`config/model.py`、`config/loader.py`、`config/secrets.py`、`domain/providers.py`、诊断服务、管理 CLI 和日志脱敏。

已完成：

- 运行时 Provider 白名单和启用列表只保留 `qwen`。
- 只读取 `DASHSCOPE_API_KEY`；doctor、诊断和日志不读取或输出豆包密钥。
- 旧本地 `.env` 中遗留的 `DOUBAO_API_KEY` 会被忽略，不进入运行环境，也不改变 Qwen-only 诊断结果。
- Agent 限制进入冻结配置模型，并支持明确白名单环境变量覆盖。

### 2.2 ToolRegistry 与 echo

实现位置：`application/agent/registry.py`、`bootstrap/container.py`。

已完成：

- Bootstrap 构造并冻结 ToolRegistry，不支持运行时注册或删除。
- 工具名称、说明长度、数量、顶层 object Schema、32 KiB Schema 大小和远程 `$ref`/`$dynamicRef` 均在启动时校验。
- 使用 `jsonschema` Draft 2020-12 校验模型参数，不把完整原始参数回显到错误消息。
- local/test 注册固定的无副作用 `echo` 工具；production 工具注册表为空。
- 工具结果必须是与 call ID 对应的纯文本 `ToolResultBlock`。

### 2.3 AgentRunService

实现位置：`application/agent/service.py`。

已完成：

- `ModelStepRunner` 消费完整模型步骤，区分最终文本、推理摘要和工具调用。
- `AgentRunService` 在同一 run 工作上下文中循环执行“模型 → 工具 → 结果回填 → 模型”。
- 同批多个工具按供应商顺序串行执行，工具事件按 `tool_call → tool_result` 交替发布。
- 未知工具、参数错误、工具异常、工具超时和无效工具结果转换为可恢复的 error `ToolResultBlock`，回填模型继续决策。
- 最大步骤、最大总调用数、单步调用数、总超时、模型步骤超时和工具超时均已生效。
- 最后一个模型步骤仍请求工具时不执行该批工具，直接以步骤限制失败。
- 文本与工具调用混合、空模型输出、重复 call ID 和上下文超限属于 run 级失败。
- 所有模型步骤都有 usage 时逐字段汇总；任一步骤缺少 usage，最终 usage 为 `null`。
- 成功只提交当前 user 和最终 assistant；工具调用、工具结果和事件不写入正式会话历史。失败和取消清理 active run 且不提交。

### 2.4 Qwen 工具协议

实现位置：`infrastructure/models/qwen/adapter.py`。

已完成：

- 标准 function `tools`、`tool_choice="auto"`、assistant `tool_calls` 和独立 tool result message 映射。
- 流式工具片段按 index 聚合，在完整 JSON object 参数解析成功后才产生 `ToolCallModelOutput`。
- 校验连续 index、唯一 call ID、稳定 id/name、function 类型、显式 finish reason 和截断终止。
- 收到工具片段后禁止自动重试；文本、usage、keepalive 和原有错误映射保持兼容。
- `ModelCapabilities.tool_calling` 和 `native_streaming` 已为 `true`；图片、音频和 reasoning summary 能力仍为 `false`。

### 2.5 Web 与页面

实现位置：`bootstrap/container.py`、`interfaces/web/app.py`、`interfaces/web/static/`。

已完成：

- 复用既有 `POST /api/v1/sessions/{session_id}/messages:stream`，不新增 Agent 路由或请求字段。
- Web SSE 直接承载 `tool_call` 和 `tool_result` 事件。
- 页面只显示工具名称和成功/错误状态，不展示完整参数、原始 JSON 或工具结果正文。
- 原有 `/api/v1/chat` 保持非流式、无工具兼容语义。

## 3. 自动化验证

### 3.1 测试结果

执行命令：

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run pytest --cov=novaagent --cov-report=term-missing -q
```

结果：`232 passed`，项目总覆盖率 `94%`。

阶段 05 核心模块覆盖率：

| 模块 | 覆盖率 |
| --- | ---: |
| `application/agent/service.py` | 97% |
| `application/agent/registry.py` | 99% |
| `infrastructure/models/qwen/adapter.py` | 90% |

关键覆盖路径包括：直接文本完成、单次和多次工具调用、同批串行顺序、未知工具、参数错误、工具异常和超时恢复、步骤/调用限制、重复 call ID、最后一步禁止执行、总超时、步骤超时、取消、上下文超限、usage 汇总规则、原子提交、失败不提交、Schema 拒绝、Qwen 非流式工具调用、流式片段聚合、DashScope 空身份占位符、非空身份冲突、协议畸形和重试边界。

### 3.2 质量门禁

以下命令均通过：

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff format .
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run ruff check .
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run mypy src tests
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache uv run pytest --cov=novaagent --cov-report=term-missing -q
git diff --check
```

依赖锁定已更新，新增 `jsonschema` 和开发期 `types-jsonschema`。测试和 CI 不访问真实千问账号，也不读取项目真实 `.env` 中的密钥值。

## 4. MockTransport Web 闭环

新增集成测试通过现有 Web SSE 路径完成：

```text
创建 session
  → Qwen 第一步返回 echo tool_call
  → ToolRegistry 执行 echo
  → Qwen 第二步收到 assistant tool_call + role=tool result
  → 最终文本和 run_completed
  → session 只保存 user + final assistant
```

测试确认：

- 第一条 Qwen 请求包含标准 function tool 和 `tool_choice="auto"`。
- 第二条请求包含正确的 assistant tool call 和独立 `role="tool"` message。
- SSE 含有 `tool_call`、`tool_result` 和 `run_completed`。
- 会话详情只包含 user/assistant 两条正式历史消息。
- 该闭环使用 `httpx.MockTransport`，没有互联网访问。

## 5. 安全与产品边界

- 不实现文件、Shell、浏览器、网络、MCP 或其他有副作用工具；这些能力进入阶段 06 或后续阶段。
- 不在 Web 请求中暴露 Provider、模型、温度、工具参数或 Agent 限制配置。
- 不把工具轨迹持久化，不把原始思维链或 `reasoning_content` 写入事件、日志和会话。
- 页面继续使用 `textContent`，不引入 Markdown、CDN 或原始 JSON 调试面板。
- production 工具注册表为空，local/test 的 `echo` 不读取文件、环境、网络、数据库或系统时间。

## 6. 真实 DashScope 协议兼容性复验

负责人首次通过 Web 请求 `echo` 时，第一步模型响应被报告为 `provider_response_invalid`。脱敏协议探测确认 DashScope 会在工具调用的后续流式分片中重复发送空字符串 `id` 作为占位符；原解析器把该空值误判为调用 ID 被修改。

修复后：

- 流式分片中的空 `id` 和空函数名按“该分片未提供身份字段”处理。
- 两个不同的非空 ID 或函数名仍被拒绝，不降低身份一致性校验。
- 已使用真实千问完成进程内 `echo` Agent 闭环，观察到 `tool_call → tool_result → text_delta → message_completed → run_completed`。
- 闭环成功后 session revision 为 `1`，正式历史角色仍只有 `user` 和 `assistant`。
- 未记录 API Key、完整提示、完整回答、工具参数或供应商原始响应。

## 7. 负责人验收

验收日期：2026-08-18。

项目负责人重启 Web 服务后，通过 local 环境和本地 `.env` 执行真实千问 Web echo。负责人确认：

- `echo` 工具调用成功。
- 最终回复明确确认工具返回内容与输入一致。
- 修复后的 Web → AgentRunService → Qwen → echo → Qwen → Web 路径可用。
- 验收记录没有写入 API Key、完整工具参数或供应商原始响应。

阶段 04 的真实 Web 验收继续提供多轮、取消和成功历史边界的运行证据；阶段 05 自动化测试提供 Agent 工具错误恢复、失败不提交、取消、步骤限制、上下文限制和工具轨迹不进入正式历史的证据。负责人接受以上组合证据，不把未在本次浏览器复验中重复执行的场景记录为新的手工演示。

验收决策：阶段 05、MOD-06、AGT-01～AGT-06 和 AGT-08 标记为“已验收”。AGT-07 不属于本阶段，继续后置。

## 8. 当前结论

截至 2026-08-18：

- 设计：已确认。
- 实现：已完成。
- 自动化测试：已完成，`232 passed`。
- MockTransport Web echo 闭环：已完成。
- 质量门禁：已完成，总覆盖率 `94%`。
- 真实千问进程内 echo 闭环：已完成。
- 修复后真实千问 Web echo：已由负责人确认通过。
- 阶段验收：已完成。

阶段结论：**阶段 05 Agent 决策循环已完成并通过验收，可以进入阶段 06“安全的本地工具”设计。**
