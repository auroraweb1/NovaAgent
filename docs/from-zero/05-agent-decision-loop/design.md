# 阶段 05 设计：Agent 决策循环

> 状态：已验收
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-18
>
> 前置阶段：阶段 04“Web 流式输出与多轮会话”已验收
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 文档目的

本文定义 NovaAgent 阶段 05“Agent 决策循环”的产品边界、运行状态机、模型步骤、工具注册与校验、工具结果回填、会话提交、事件语义、Qwen 工具调用映射、取消与超时、错误恢复、Web 最小呈现、测试方案和验收门禁。

阶段 05 的目标不是增加真实文件、Shell、浏览器或网络工具，而是在阶段 02 的统一协议、阶段 03 的真实千问 Adapter 和阶段 04 的流式多轮会话之上，建立一条可确定性测试的 Agent 主循环：

```text
浏览器文本输入
  → AgentRunService
  → 选择会话历史并构造本次 run 工作上下文
  → 千问产生最终文本或工具调用
  → ToolRegistry 校验并执行工具
  → 工具结果回填本次 run 工作上下文
  → 千问继续决策
  → 最终文本流式返回 Web
  → 成功后原子提交 user / final assistant
```

项目负责人已确认第 24 节 D05-01 ～ D05-24。阶段 05 已按本文完成实现、自动化验证、真实千问协议复验和 Web echo 验收，并于 2026-08-18 标记为“已验收”。

## 2. 已确认的产品范围

阶段 04 验收后的产品范围变更继续生效：

- 千问是唯一模型 Provider。
- Web 控制台是唯一用户聊天入口。
- 不接入豆包或其他第二模型 Provider。
- 不建设图片、音频、视频等模型多模态任务。
- Provider API Key 只由服务端环境或 Git 忽略的本地 `.env` 提供，Web 永不管理密钥。
- 原始思维链和 `reasoning_content` 不展示、不保存、不记录、不回填上下文。

阶段 05 编码前已完成进度矩阵 MOD-06：运行时配置、诊断、CLI 和测试仅保留千问；旧本地 `.env` 中的豆包键会被忽略，不会进入运行环境或诊断输出。

## 3. 前置能力

### 3.1 阶段 02 协议

现有领域协议已经提供：

- `ToolDefinition`：工具名称、说明和 JSON Schema 参数。
- `ToolCallBlock`：`call_id`、`tool_name` 和不可变 JSON 参数。
- `ToolResultBlock`：成功或失败状态、内容和可选错误码。
- `ToolPort`：工具定义和异步执行接口。
- `ToolExecutionContext`：run、session 和只读元数据。
- `ToolCallModelOutput`：模型请求工具的供应商无关输出。
- `ToolCallPayload`、`ToolResultPayload` 和 `ArtifactPayload`。
- AgentEvent 顺序、终止语义和 JSON 协议版本 `1`。

### 3.2 阶段 03 千问 Adapter

现有 Qwen Adapter 已经固定：

- 官方 Base URL 和 `/chat/completions` 路径。
- `qwen3.8-max` 默认模型。
- HTTPX 生命周期、并发额度、超时、有限重试和稳定错误映射。
- 非流式与流式文本响应解析。
- `enable_thinking=false` 和原始推理字段拒绝。

当前 Adapter 已扩展 `tools`、tool role message 和供应商 `tool_calls`，同时保持固定地址、密钥来源、文本安全、thinking 关闭和重试原则。

### 3.3 阶段 04 会话与 Web

现有多轮路径已经提供：

- 内存 Session Store、revision 和同会话单活动 run。
- `POST /api/v1/sessions/{session_id}/messages:stream`。
- `POST /api/v1/runs/{run_id}/cancel`。
- POST + `fetch` 读取 SSE。
- 客户端断开后取消上游请求。
- 成功后 user/assistant 原子提交，失败和取消不提交。
- 最近 20 个完整轮次和 24,000 estimated token 上下文预算。

阶段 05 必须保持这些接口和会话不变量。

## 4. 本阶段目标

阶段 05 必须完成：

1. 实现 `AgentRunService` 和有限 Agent 决策循环。
2. 实现启动后冻结的 `ToolRegistry`。
3. 使用成熟 JSON Schema 实现校验工具定义和模型参数。
4. 实现一个无网络、无文件、无环境读取、无副作用的诊断示例工具。
5. 扩展 Qwen Adapter 的工具定义、工具调用和工具结果消息映射。
6. 支持一个模型步骤产生一个或多个完整工具调用。
7. 按供应商返回顺序串行执行同批工具调用。
8. 将成功或失败的工具结果回填到同一次 run 的模型上下文。
9. 支持模型在工具结果后继续调用工具或生成最终文本。
10. 实现最大模型步骤、最大工具调用数、总超时、模型步骤超时和工具超时。
11. 实现未知工具、参数非法、工具失败和工具超时的可恢复结果。
12. 保持 run 取消、客户端断开和 Provider 失败的终止语义。
13. 在 Web 中最低限度显示工具名称和执行状态，不展示完整参数或结果。
14. 使用脚本化模型、MockTransport 和真实千问完成分层验收。

## 5. 非目标

阶段 05 明确不做：

- 不实现 `ls`、`read`、`write`、`edit`、`bash`、浏览器、网络或 MCP 工具；进入阶段 06 或阶段 12。
- 不允许工具访问文件系统、进程环境、网络、数据库或外部服务。
- 不实现危险操作确认、路径沙箱、写入事务和 Shell 安全；进入阶段 06。
- 不实现真正的并行工具执行；阶段 05 只接受多调用批次并确定性串行执行。
- 不实现运行中追加指令或 Steering；AGT-07 继续留到阶段 13 或后续。
- 不持久化完整 Agent run、工具轨迹或事件流；进入阶段 10。
- 不把工具调用和工具结果写入正式会话历史。
- 不实现工具动态安装、插件发现、Skills、MCP 或运行时热更新。
- 不实现图片、音频、视频、Vision、ASR、TTS 或图像生成。
- 不实现完整工具卡片、参数展开、产物预览或运行调试面板；进入阶段 07。
- 不允许 Web 选择工具、Provider、模型、温度或步骤限制。
- 不开放任意用户自定义 JSON Schema 或用户上传 Python 工具。
- 完成报告在自动化实现和 MockTransport 验证完成后创建；真实千问 Web 验收结论由负责人确认后补充。

## 6. 关键领域语义

### 6.1 Run、模型步骤和工具批次

术语定义：

- **Agent Run**：一次用户输入从开始到成功、失败或取消的完整生命周期。
- **模型步骤（model step）**：对千问发起一次请求并完整消费一次响应。
- **工具批次（tool batch）**：同一个模型步骤返回的一个或多个工具调用。
- **工具执行（tool execution）**：一个工具调用从校验到产生 `ToolResultBlock` 的过程。
- **最终回答**：不包含工具调用且含有有意义文本的模型步骤结果。

`max_steps` 统计模型请求次数，不统计工具数量。一次模型步骤只能有两种合法结果：

1. 最终文本，结束 run。
2. 一个或多个工具调用，执行并回填后进入下一模型步骤。

同一模型步骤同时产生有意义文本和工具调用属于非法供应商输出。阶段 05 不把工具调用前的临时文字冒充最终回答，也不接受混合语义。

### 6.2 Run 工作上下文

阶段 05 区分两类消息：

- **正式会话历史**：阶段 04 已成功提交的 user/final assistant 完整轮次。
- **本次 run 工作上下文**：选中的正式历史、当前 user、模型工具调用消息和 tool result message。

工作上下文只存在于当前协程内，不写入 Session Store。每次工具执行后，下一次模型请求按以下顺序组装：

```text
已选择的正式历史
  → 当前 user message
  → assistant(tool_call...)
  → tool(tool_result)
  → 可选更多 assistant/tool 步骤
```

模型产生最终文本后，Session Store 仍只提交：

```text
current user
final assistant
```

这样保持 `SessionSnapshot` 的偶数消息、user/assistant 成对结构、阶段 04 上下文裁剪和 revision 事务不变。阶段 10 若需要审计或恢复完整 run，应建立独立 Run Store，不能把工具轨迹混入聊天轮次。

### 6.3 成功、失败和取消提交

- 只有 `run_completed` 后提交 user/final assistant。
- 未知工具或工具失败本身不终止 run；它们先变成 error `ToolResultBlock` 回填模型。
- 模型在收到错误结果后可以改用其他工具或直接回答。
- 达到步骤、调用数、上下文或总时间限制时 run 失败，不提交本轮。
- Provider 失败、协议非法、用户取消和客户端断开均不提交本轮。
- 工具执行期间取消必须传播到工具协程，并最终产生一个 `run_cancelled`。

## 7. Agent 状态机

推荐状态：

```text
CREATED
  → CONTEXT_PREPARED
  → MODEL_RUNNING
      ├─ final text → FINALIZING → COMPLETED
      ├─ tool batch → TOOLS_RUNNING → MODEL_RUNNING
      ├─ provider/protocol/limit error → FAILED
      └─ cancellation → CANCELLED
```

伪代码：

```text
prepare initial context
mark session active run
publish run_started + context_prepared

within total timeout:
  for step_index in 1..max_steps:
    ensure working context fits budget
    outcome = run one Qwen model step with registered tool definitions

    if outcome is final text:
      publish final message events
      publish run_completed with aggregated usage
      atomically commit user/final assistant
      return

    if step_index == max_steps:
      fail agent_step_limit_reached without executing new tool calls

    validate batch count and run total call count
    append assistant tool-call message to working context

    for call in provider order:
      publish tool_call
      result = validate and execute with timeout
      publish tool_result
      append tool result message to working context

fail if the loop exits without a final answer
```

无论成功、失败或取消，`finally` 都必须移除 ActiveRunRegistry 条目并清除 Session Store 的 `active_run_id`。

## 8. 模型步骤设计

### 8.1 独立的 ModelStepRunner

现有 `run_protocol()` 同时承担“消费一次模型流”和“终止整个 run”，不适合直接包裹多步骤循环。阶段 05 推荐提取内部 `ModelStepRunner`：

```text
ModelStepRunner.run(request) -> ModelStepOutcome
```

结果联合类型：

```text
FinalTextOutcome(text, usage)
ToolCallsOutcome(calls, usage)
```

职责：

- 消费一次 `ModelPort.stream()`。
- 聚合文本、完整工具调用和 usage。
- 拒绝文本与工具调用混合。
- 拒绝空输出、重复 call ID 和超量工具批次。
- 不提交会话，不执行工具，不发布 run 终止事件。

`AgentRunService` 负责跨步骤状态、事件序号、工具执行、最终消息和终止事件。阶段 03 单轮 API 可继续使用现有 `run_protocol()`，避免无关回归。

### 8.2 最终文本流式展示

工具决策步骤不允许有可见文本，因此工具调用可以先完整聚合再发布。最终文本步骤继续逐段发布 `text_delta`，保留阶段 04 用户体验。

`message_started` 延迟到最终文本步骤的第一个有效文本 delta 前发布。工具决策步骤不创建可见 assistant message。

### 8.3 Usage 聚合

一次 Agent Run 可能调用千问多次：

- 每个模型步骤最多记录一个 usage。
- 所有步骤均返回 usage 时，`run_completed.usage` 为逐字段求和。
- 任一步骤缺少 usage 时，最终 usage 为 `null`，不返回可能被误解为完整账单的部分合计。
- 失败和取消不发布 `run_completed`，但内部结构化日志可以记录已知的非正文计数。

## 9. ToolRegistry 设计

### 9.1 注册规则

推荐新增：

```text
ToolRegistry(tools: Sequence[ToolPort])
  definitions() -> tuple[ToolDefinition, ...]
  resolve(name: str) -> ToolPort
```

规则：

- Bootstrap 构造后冻结，不支持运行时注册和删除。
- 工具名称全局唯一。
- 名称匹配 `^[a-z][a-z0-9_]{0,63}$`。
- description 去除首尾空白后长度为 1～1024。
- parameters 必须是合法 JSON Schema，顶层 `type` 必须为 `object`。
- 单个 Schema 序列化后最大 32 KiB。
- 最多注册 32 个工具。
- 禁止远程 `$ref`、`$dynamicRef` 和会触发网络解析的引用。
- 重复名称或非法定义在 Bootstrap 启动时失败，不等到模型调用后才发现。

### 9.2 JSON Schema 校验

阶段 05 推荐新增 `jsonschema>=4.23,<5`，使用 Draft 2020-12 校验定义和调用参数。原因是 JSON Schema 的组合、数值、数组、枚举和 additionalProperties 语义不应由 NovaAgent 手写。

参数错误只返回：

- 稳定错误码 `tool_arguments_invalid`。
- 最短字段路径。
- 面向模型的简洁说明。

不回显完整参数，不把 Python 异常或 Schema 内部堆栈发送给模型、Web 或日志。

## 10. 诊断示例工具

阶段 05 只实现一个 `echo` 工具，用于证明完整循环：

```json
{
  "name": "echo",
  "description": "Return the supplied text unchanged for Agent loop diagnostics.",
  "parameters": {
    "type": "object",
    "properties": {
      "text": {"type": "string", "minLength": 1, "maxLength": 2000}
    },
    "required": ["text"],
    "additionalProperties": false
  }
}
```

边界：

- 不访问文件、环境、网络、数据库或系统时间。
- 不产生 Artifact。
- 结果只有一个 `TextBlock`。
- local 和 test 环境注册，用于自动化与真实 Web 验收。
- production 环境不注册诊断工具；阶段 06 提供真实受控工具后再开放生产工具集。
- 工具名称和说明由服务端固定，Web 用户不能修改。

## 11. 工具执行语义

### 11.1 顺序

一个模型步骤可以返回多个工具调用。阶段 05 按供应商 `index` 和出现顺序串行执行：

```text
call[0] → result[0] → call[1] → result[1]
```

不使用 `asyncio.gather()` 并行执行。阶段 06 的文件、命令和其他有副作用工具需要权限、锁和冲突策略；在这些元数据出现前并行会扩大风险。未来只有显式声明 parallel-safe 的只读工具才可以进入有界并行设计。

### 11.2 可恢复错误

以下问题转换为 error `ToolResultBlock` 并继续下一模型步骤：

| 错误码 | 条件 | 返回模型的公开信息 |
| --- | --- | --- |
| `tool_not_found` | 模型请求未注册工具 | 工具不可用，请改用已提供工具或直接回答 |
| `tool_arguments_invalid` | 参数不满足 Schema | 参数无效和最短字段路径 |
| `tool_timeout` | 单次执行超过限制 | 工具执行超时 |
| `tool_execution_failed` | 工具抛出预期执行错误 | 工具未能完成请求 |
| `tool_result_invalid` | 工具返回不符合 Port 契约 | 工具结果无效 |

工具异常的原始文本、类型、堆栈和敏感参数不进入结果。未知工具仍计入本次 run 的工具调用总数，防止模型通过反复猜测绕过上限。

### 11.3 系统级失败

以下情况终止 run，而不是伪装成普通工具错误：

- ToolRegistry 自身损坏或重复注册漏过启动校验。
- Event Sink 不可用。
- Session revision 或活动 run 不变量被破坏。
- 工具结果无法安全序列化且无法构造稳定错误结果。
- Agent 总超时、步骤上限、调用总数上限或上下文预算耗尽。

## 12. 限制与超时

推荐在 TOML 增加服务端只读配置：

```toml
[agent]
max_steps = 8
max_tool_calls = 16
max_tool_calls_per_step = 8
total_timeout_seconds = 180
model_step_timeout_seconds = 75
tool_timeout_seconds = 10
```

约束：

| 配置 | 默认值 | 允许范围 | 语义 |
| --- | ---: | ---: | --- |
| `max_steps` | 8 | 1～32 | 单次 run 最大模型请求数 |
| `max_tool_calls` | 16 | 1～64 | 单次 run 最大工具调用总数 |
| `max_tool_calls_per_step` | 8 | 1～16 | 单个模型响应最大工具调用数 |
| `total_timeout_seconds` | 180 | 10～900 | 包含模型、工具和本地编排 |
| `model_step_timeout_seconds` | 75 | 1～300 | 单次模型步骤上限 |
| `tool_timeout_seconds` | 10 | 1～120 | 单次工具执行上限 |

这些设置不通过 Web 修改。环境变量覆盖遵循现有 `NOVAAGENT_*` 明确白名单，不接受未知键。

稳定 run 级错误：

| 错误码 | 条件 | retryable |
| --- | --- | --- |
| `agent_step_limit_reached` | 需要更多模型步骤才能完成 | 否 |
| `agent_tool_call_limit_reached` | 工具调用批次或总数超限 | 否 |
| `agent_timeout` | 总运行时间超限 | 是 |
| `agent_model_step_timeout` | 单次模型步骤超限 | 是 |
| `agent_context_limit_reached` | 本次工具轨迹使工作上下文超过预算 | 否 |
| `agent_model_output_invalid` | 模型步骤为空或混合文本/工具调用 | 是 |

达到最后一个模型步骤且模型仍请求工具时，不执行该批工具，直接以 `agent_step_limit_reached` 失败，避免产生无法回填给下一模型步骤的副作用。

## 13. 上下文预算

阶段 04 的历史裁剪仍按完整 user/assistant 轮次执行。阶段 05 增加 run 内预算检查：

- 每次模型步骤前估算完整工作上下文。
- 估算必须包含 ToolCall 参数 JSON、ToolResult 文本、角色和固定消息开销。
- 已经进入本次 run 的工具轨迹不能从中间静默删除，否则模型会看到不完整调用链。
- 超过 24,000 estimated token 预算时返回 `agent_context_limit_reached`。
- 单个工具结果最多保留 16,000 个 Unicode 字符，超出时添加明确截断标记；阶段 06 再形成统一工具输出截断组件。
- 不把 estimated token 当作供应商账单 usage。

`context_prepared` 继续描述初始正式历史选择。阶段 05 不新增包含正文的上下文事件。

## 14. AgentEvent 语义

阶段 05 继续使用协议版本 `1`，不建立第二套 Agent 流协议。推荐事件序列：

```text
run_started
context_prepared
tool_call
tool_result
tool_call
tool_result
message_started
text_delta...
message_completed
run_completed
```

失败：

```text
run_started
...
error
run_failed
```

取消：

```text
run_started
...
run_cancelled
```

本阶段不新增 `tool_started` 或 `tool_progress`：

- `tool_call` 表示调用已经通过模型步骤校验并即将执行。
- `tool_result` 表示成功、可恢复错误或超时的完成结果。
- 长任务进度只有在阶段 06/12 出现真实长运行工具后才设计，避免创建没有生产者的事件。

加强 `EventSequenceValidator`：

- `call_id` 在一个 run 内唯一。
- 每个 `tool_call` 最多且必须对应一个 `tool_result`，除非 run 在执行中取消或失败。
- 同一个 `call_id` 不允许重复结果。
- 最终 `message_started` 后不允许再出现 `tool_call`。
- `run_completed` 前不得存在未完成工具调用。
- error 仍必须紧邻 `run_failed`。

### 14.1 Artifact 边界（AGT-08）

`ArtifactPayload` 和 `FileRefBlock` 已在阶段 02 定义。阶段 05 只补充契约测试和范围说明：

- Artifact 只代表由受控工具产生的可下载资源引用。
- 阶段 05 `echo` 不产生 Artifact。
- 图片、音频和视频不作为模型多模态输入。
- 阶段 06 的文本文件工具可以产生 Artifact；阶段 07 再提供 Web 可视化和下载交互。
- Artifact 不能绕过工作空间、归属和权限检查。

## 15. Qwen Adapter 工具调用

### 15.1 请求映射

`ToolDefinition` 映射到 OpenAI-compatible function tool：

```json
{
  "type": "function",
  "function": {
    "name": "echo",
    "description": "...",
    "parameters": {"type": "object", "properties": {}}
  }
}
```

请求规则：

- 有注册工具时发送 `tools` 和 `tool_choice="auto"`。
- 不向 Web 暴露 `tool_choice`。
- 继续发送 `enable_thinking=false`。
- 不发送图片、音频、并行工具开关或自定义供应商参数。

消息映射：

- 普通 system/user/assistant 文本保持现有映射。
- assistant `ToolCallBlock` 映射为 `tool_calls`，content 为 `null` 或供应商要求的空值。
- 每个 tool `ToolResultBlock` 映射为独立 `role="tool"` message，包含 `tool_call_id` 和纯文本 content。
- 阶段 05 拒绝工具结果中的图片、音频、文件引用和嵌套 ToolCall。

### 15.2 流式工具调用解析

供应商可能把一个工具调用拆成多个 SSE delta。Adapter 使用请求内局部 accumulator，按 `index` 聚合：

- `id`
- `function.name`
- `function.arguments` 字符串片段

完成时要求：

- index 从 0 开始、非负且不重复冲突。
- 同一 index 的 id 和 name 不得变化。
- call ID 和工具名非空。
- arguments 能解析为 JSON object，不接受数组、标量或尾随文本。
- `finish_reason` 与工具调用/最终文本形状一致。
- 重复 call ID、未知字段类型、截断 EOF 或 `[DONE]` 缺失稳定失败。

Adapter 只在一个调用完整后产生 `ToolCallModelOutput`，不把 JSON 参数碎片发布为 AgentEvent。

### 15.3 重试

- 首个文本 delta 或首个工具调用片段之前允许现有有限重试。
- 收到任意工具调用片段后禁止自动重试，即使尚未执行工具，避免重复模型决策和费用。
- 工具已经执行后，下一模型步骤是新的独立请求；失败时整个 run 失败，不自动重放已执行工具。
- Provider 并发额度覆盖每个模型步骤，等待工具执行时释放模型连接和额度。

实现完成后 `ModelCapabilities.tool_calling=true`；图片和音频能力继续为 `false`。

## 16. Web API 与页面

### 16.1 API 兼容

继续使用：

```text
POST /api/v1/sessions/{session_id}/messages:stream
POST /api/v1/runs/{run_id}/cancel
```

请求 Schema、鉴权、revision、SSE 响应头、keepalive、队列背压和终端事件不变。路由内部从 `MultiTurnChatService` 迁移到 `AgentRunService`，而不是创建第二条 `/agent` 聊天 API。

保留阶段 03 `POST /api/v1/chat` 非流式、无工具兼容路径。

### 16.2 Web 最小呈现

阶段 05 在现有消息区增加轻量运行活动列表：

- `tool_call`：显示“正在运行 {tool_name}”。
- success `tool_result`：显示“{tool_name} 已完成”。
- error `tool_result`：显示工具名和稳定错误码对应的友好状态。
- 不显示完整 arguments、完整 result、Schema、异常或堆栈。
- 最终 assistant 文本继续逐段显示。
- 失败或取消活动标记为临时，不进入刷新后的正式历史。

阶段 05 不建设嵌套卡片、调试树、原始 JSON、复制参数或重新执行按钮；阶段 07 再设计完整工具过程 UI。

## 17. 取消、断开与并发

- 同一会话仍只允许一个活动 run，不排队。
- 不同会话可以并发运行，各自拥有独立工作上下文和工具实例调用。
- `ActiveRunRegistry` 继续以 run ID 取消当前 Agent task。
- 取消模型步骤必须关闭 Qwen 上游流。
- 取消工具步骤必须取消工具协程并停止等待。
- 客户端断开原因仍为 `client_disconnected`，用户按钮仍为 `user_requested`。
- 取消不转换为工具错误结果，不继续调用模型。
- `run_cancelled` 之后不得发布工具结果、文本或其他终止事件。
- ToolRegistry 是只读共享对象；ToolPort 若包含可变状态，必须由实现自行同步。阶段 05 `echo` 无可变状态。

## 18. 日志与安全

结构化日志允许：

- request ID、run ID、session ID。
- step index、工具名、调用序号、状态和耗时。
- 错误码、Provider 状态、usage 计数和是否截断。

默认禁止：

- 完整用户输入和最终回答。
- 完整工具参数和工具结果。
- Qwen 原始请求、响应、SSE data 和 tool arguments 字符串。
- API Key、Web Token、环境快照和异常堆栈的用户可见输出。
- 原始思维链和 `reasoning_content`。

工具公开错误使用固定消息。内部异常可以通过 `logger.exception` 关联 request/run ID，但不得把参数或结果作为结构化字段。

## 19. 测试设计

### 19.1 ToolRegistry 与 Schema

- 合法定义注册并保持确定顺序。
- 重复名称、非法名称、空说明、超大 Schema 和非 object Schema 拒绝。
- 远程 `$ref` 和 `$dynamicRef` 拒绝。
- required、additionalProperties、enum、数组和嵌套对象参数验证。
- 未知工具返回 `tool_not_found`。
- 原始非法参数不进入公开错误。

### 19.2 AgentRunService 单元测试

- 第一步直接文本完成。
- 一次工具调用后文本完成。
- 多轮工具调用后文本完成。
- 一个批次多个调用按顺序执行。
- 未知工具结果回填后模型恢复。
- 参数非法、工具失败和工具超时回填后模型恢复。
- 模型空输出和文本/工具混合失败。
- 重复 call ID 和超量调用失败。
- 达到最后步骤时不执行新工具批次。
- 总超时、模型步骤超时和取消。
- 工具结果导致上下文超限。
- usage 全部存在时求和，任一缺失时为 null。
- 成功只提交 user/final assistant。
- 失败和取消不提交，会话 active run 必须清理。

### 19.3 事件契约

- `tool_call → tool_result` 一一对应。
- 多批次顺序和 sequence 连续。
- 未完成工具调用不能 `run_completed`。
- 最终 message 后不能再调用工具。
- 取消期间允许存在没有结果的最后一个 tool call，但终止后无事件。
- 工具错误不产生 run 级 `error`，除非最终达到 Agent 限制或系统失败。
- Artifact 仍能协议版本 `1` 往返，但阶段 05 不生产。

### 19.4 Qwen MockTransport

- 请求包含标准 function tools 和 `tool_choice=auto`。
- assistant tool call 和 tool result message 映射正确。
- 非流式完整 `tool_calls` 解析。
- 流式单调用和多调用碎片聚合。
- arguments 跨多个 chunk 拼接。
- role-only、usage-only 和 keepalive 处理。
- 非 object arguments、重复 index/id、变化 name、混合文本、截断 EOF 和非法 finish reason 拒绝。
- 工具片段后禁止重试。
- 阶段 03 非流式文本和阶段 04 流式文本全部回归。

### 19.5 Web 集成

- 原 SSE 路径通过 AgentRunService 完成 echo 循环。
- 工具事件直接承载 AgentEvent JSON。
- 页面不需要新请求字段。
- revision、同会话 busy、取消、断开和错误信封回归。
- 刷新后只显示 user/final assistant，不显示 run-local 工具轨迹。
- 非流式 `/api/v1/chat` 不发送 tools。

### 19.6 质量门禁

- 全项目覆盖率不低于 80%。
- AgentRunService、ToolRegistry、Schema 校验和 Qwen tool mapper 各不低于 90%。
- Pytest、Ruff、Mypy 和 `git diff --check` 全部通过。
- 自动化和 CI 不访问真实千问。
- 测试不得读取项目真实 `.env` 或输出密钥。

## 20. 验收演示

### 20.1 无网络确定性演示

使用脚本化模型：

```text
user: 必须使用 echo 处理 stage-five-probe
  → model step 1: echo({"text":"stage-five-probe"})
  → echo result: stage-five-probe
  → model step 2: 最终文本
  → run_completed
  → session revision +1
```

验证请求次数、工作上下文顺序、事件序列、最终历史和 usage 聚合。

### 20.2 MockTransport 千问协议演示

使用供应商形状的流式假响应完成：

```text
Qwen tool_call fragments
  → Adapter accumulator
  → ToolCallModelOutput
  → echo
  → Qwen tool result request
  → final text deltas
```

不得访问互联网或真实账号。

### 20.3 真实千问 Web 演示

项目负责人使用本地 `.env` 和 local 环境：

1. 创建一个新会话。
2. 明确要求模型调用 `echo`，参数使用不含敏感信息的固定探针文本。
3. 确认页面先显示工具运行状态，再逐段显示最终回答。
4. 确认第二轮仍能使用上一轮最终回答上下文。
5. 触发一次停止生成，确认取消后不提交本轮。
6. 确认刷新后只保留成功的 user/final assistant。
7. 确认页面、日志和文档没有 API Key、完整工具参数、原始 SSE 或思维链。

验收记录只写成功/失败、步骤数、工具状态、usage 是否完整和取消是否生效，不记录密钥、完整问题、完整结果或供应商原始响应。

验收结果（2026-08-18）：负责人确认修复后的真实千问 Web echo 调用成功，最终回复明确表示工具返回内容与输入一致。阶段 04 的真实 Web 会话验收与阶段 05 的自动化测试继续作为多轮、取消、历史提交和失败路径证据；本次不把未重复手工执行的场景记录为新的人工演示。

## 21. 实现顺序

1. 完成 MOD-06，删除豆包配置、密钥和诊断兼容面及相关测试。
2. 增加 Agent 配置模型、TOML/环境覆盖和失败路径测试。
3. 收紧 `ToolDefinition`，实现 ToolRegistry 和 JSON Schema 校验。
4. 实现 local/test `echo` ToolPort。
5. 实现 ModelStepOutcome 和 ModelStepRunner。
6. 实现 AgentRunService、run 工作上下文、限制、usage 聚合和提交事务。
7. 加强 AgentEvent 顺序校验和协议往返测试。
8. 扩展 Qwen 请求映射和非流式工具调用解析。
9. 实现流式 tool_calls accumulator 和重试边界。
10. 用 AgentRunService 替换 Web 多轮流式路由内部服务，保持 API 不变。
11. 增加 Web 最小工具状态呈现。
12. 完成单元、契约、集成和 MockTransport 测试。
13. 更新 README、总体路线、进度矩阵并创建完成报告。
14. 运行全部质量门禁。
15. 由项目负责人完成真实千问 Web 验收。

每一步先完成最窄测试，再运行受影响回归；完成第 14 步前不标记“已实现”，完成第 15 步前不标记“已验收”。

## 22. 设计差异与兼容策略

| 现有实现 | 阶段 05 处理 | 原因 |
| --- | --- | --- |
| `run_protocol()` 一次流即终止 run | 提取 ModelStepRunner，AgentRunService 管理多步骤 | 避免让单步驱动递归调用自身 |
| Session 只存 user/assistant 对 | 保持不变，工具轨迹仅 run-local | 保持阶段 04 revision、裁剪和历史不变量 |
| Qwen Adapter 拒绝 tools | 在同一 Adapter 内增加标准 function mapping | 不建立第二个 Qwen 调用链 |
| ToolCall/ToolResult 已存在 | 复用并加强顺序契约 | 保持协议版本 `1` |
| Web 已有流式消息 API | 路径和请求不变，内部切换 AgentRunService | 避免两个聊天入口和前端分支 |
| CowAgent Agent 对象职责宽 | 拆分服务、步骤 runner、registry 和工具 Port | 防止工作空间、记忆和工具全部进入一个对象 |
| 旧项目支持并行工具 | 阶段 05 确定性串行 | 真实副作用工具尚无并发安全元数据 |

## 23. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 模型无限调用工具 | 最大步骤、总调用数、总超时和上下文预算 |
| 最后一步产生无法消费的工具结果 | 最后步骤请求工具时不执行，直接稳定失败 |
| 工具异常泄露内部信息 | 固定错误码和消息，不回显异常与完整参数 |
| 工具轨迹破坏会话成对结构 | 只在 run-local 上下文保留工具消息 |
| 工具失败导致整轮无意义失败 | 可恢复 ToolResult 回填模型继续决策 |
| 多工具并行造成冲突 | 阶段 05 串行执行，后续要求 parallel-safe 声明 |
| Qwen 流式 JSON 参数碎片非法 | 按 index 聚合，完成后结构化 JSON 解析和 Schema 校验 |
| 工具调用片段后重试造成重复 | 收到任意 tool fragment 后禁止自动重试 |
| 工具结果撑爆上下文 | 结果上限、逐步预算检查和稳定超限失败 |
| 临时工具轨迹刷新后消失造成误解 | 页面只把它显示为本次运行活动，正式历史只显示最终轮次 |
| echo 被误认为正式生产工具 | 仅 local/test 注册，production 不注册 |
| 原始思维链借工具参数泄漏 | thinking 关闭、参数不完整展示、日志白名单 |
| 阶段 05 提前建设阶段 06 安全系统 | 示例工具严格无副作用，真实工具全部后置 |

## 24. 推荐决策

| 编号 | 决策 | 推荐答案 | 状态 |
| --- | --- | --- | --- |
| D05-01 | Provider 范围 | 千问唯一；编码前先完成 MOD-06 豆包清理 | 已落实 |
| D05-02 | Web API | 复用现有会话 SSE 路径，不新增 `/agent` 聊天入口 | 已落实 |
| D05-03 | 应用服务 | 新增 AgentRunService，内部使用独立 ModelStepRunner | 已落实 |
| D05-04 | 正式会话历史 | 成功只提交 user 和最终 assistant | 已落实 |
| D05-05 | 工具轨迹 | 只存在于当前 run 工作上下文和事件流 | 已落实 |
| D05-06 | 工具注册 | Bootstrap 构造后冻结，不支持运行时动态注册 | 已落实 |
| D05-07 | 参数校验 | 使用 jsonschema Draft 2020-12，禁止远程引用 | 已落实 |
| D05-08 | 示例工具 | local/test 注册无副作用 echo，production 不注册 | 已落实 |
| D05-09 | 多工具批次 | 接受多个调用，按供应商顺序串行执行 | 已落实 |
| D05-10 | 并行工具 | 阶段 05 不实现，等待安全元数据和真实工具场景 | 已落实 |
| D05-11 | 工具失败 | 转为 error ToolResult 回填模型，允许恢复 | 已落实 |
| D05-12 | 系统失败 | 限制、协议、会话和基础设施错误终止 run | 已落实 |
| D05-13 | 默认限制 | 8 模型步骤、16 总调用、每步 8 调用、180 秒总超时 | 已落实 |
| D05-14 | 工具超时 | 每次默认 10 秒，取消必须传播 | 已落实 |
| D05-15 | 上下文 | 每个模型步骤前检查完整 run 工作上下文预算 | 已落实 |
| D05-16 | 事件协议 | 复用 tool_call/tool_result，不提前增加 progress 事件 | 已落实 |
| D05-17 | Usage | 所有模型步骤都有 usage 才求和，否则最终为 null | 已落实 |
| D05-18 | Qwen 工具模式 | 标准 function tools、tool_choice=auto、thinking 关闭 | 已落实 |
| D05-19 | Qwen 流式解析 | 按 index 聚合完整调用后才产生 ToolCallModelOutput | 已落实 |
| D05-20 | 混合模型输出 | 同一步文本和工具调用并存时稳定失败 | 已落实 |
| D05-21 | Artifact | 阶段 05 只维护文本文件引用契约，不生产或可视化产物 | 已落实 |
| D05-22 | Web 展示 | 只显示工具名和状态，不显示完整参数、结果和原始 JSON | 已落实 |
| D05-23 | 验收证据 | 脚本化模型 + MockTransport + 真实千问 Web echo 演示 | 已验收 |
| D05-24 | 编码门禁 | 本文整体确认后才实现；真实演示前保持待验收 | 已落实 |

## 25. 当前结论

阶段 01～04 已完成验收，阶段 05 的前置协议、真实千问路径、流式 Web 和会话事务均已具备。本文已经为 Agent 循环、工具注册、参数校验、Qwen tool calls、工作上下文、历史提交、错误恢复、步骤限制、取消、事件、Web 和验收方式给出推荐答案。

当前状态为“已验收”。验收证据由以下部分组成：

1. `232 passed`、94% 总覆盖率、Ruff、Mypy 和 `git diff --check`。
2. 脚本化模型和 MockTransport Web echo 闭环。
3. 修复后的真实千问进程内 `echo` Agent 闭环。
4. 项目负责人确认真实千问 Web echo 调用成功，最终回复确认返回内容与输入一致。

阶段 05、MOD-06、AGT-01 ～ AGT-06 和 AGT-08 已更新为“已验收”；AGT-07 Steering 继续后置到阶段 13 或以后。下一阶段可以进入阶段 06“安全的本地工具”设计。
