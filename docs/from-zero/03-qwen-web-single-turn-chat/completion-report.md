# 阶段 03 完成报告：千问接入与 Web 单轮聊天

> 状态：已实现；已测试；已验收
>
> 创建日期：2026-08-17
>
> 最近更新：2026-08-17
>
> 设计文档：[design.md](./design.md)
>
> 项目根目录：`/Users/jiaojie/NovaAgent`

## 1. 报告目的

本文记录阶段 03 的实际实现、自动化测试、MockTransport 无网络演示、真实千问 Web 验收、覆盖率和设计差异。

阶段 03 的代码、自动化质量门禁和真实千问 Web 单轮演示均已完成。项目负责人确认页面、真实回答、模型元信息、usage、输入校验、单轮语义和安全边界表现正常，因此本报告将阶段状态记录为“已验收”，并允许阶段 04 进入设计。

本阶段没有实现豆包、流式输出、多轮会话、SessionStore、工具、Markdown、多模态或 Web 密钥管理。以上能力仍按总体路线留在后续阶段。

## 2. 当前阶段结论

阶段 03 已完成以下可重复闭环：

```text
浏览器/HTTP 文本请求
  → Web Schema、鉴权和大小限制
  → SingleTurnChatService
  → 单条 user Message / ModelRequest
  → run_protocol / AgentEvent
  → QwenModelAdapter
  → 固定 DashScope 官方 chat/completions 地址
  → httpx.MockTransport 模拟供应商响应
  → TextModelDelta / UsageModelOutput
  → 最终 assistant Message
  → ChatResponse JSON
  → Web 页面纯文本展示
```

自动化结果：

1. 155 项测试全部通过。
2. 项目总覆盖率为 95%，超过 80% 门禁。
3. `SingleTurnChatService` 覆盖率为 100%。
4. `QwenModelAdapter` 覆盖率为 93%，超过核心模块 90% 门禁。
5. Web 应用模块覆盖率为 98%。
6. Ruff 格式与静态检查、Mypy、Pytest、doctor 和 `git diff --check` 全部通过。
7. 自动化测试没有访问互联网，没有调用真实千问 API，也没有读取或写入真实 API Key。
8. 真实千问 Web 单轮演示已由项目负责人执行并确认通过，阶段结论为“已验收”。

## 3. 已交付内容

### 3.1 千问配置和产品边界（MOD-04、MOD-05）

实现位置：

- `src/novaagent/config/model.py`
- `src/novaagent/config/loader.py`
- `src/novaagent/domain/models.py`

已实现：

- 默认 Provider 固定为 `qwen`，默认模型固定为 `qwen3.8-max`。
- 阶段 03 要求启用列表包含 `qwen`，豆包尚不能成为默认 Provider。
- 千问模型名要求以 `qwen` 开头，最长 128 字符，只允许小写字母、数字、点、下划线和连字符。
- `temperature`、`max_output_tokens`、`timeout_seconds`、`max_retries` 和 `max_concurrency` 具有明确默认值和上下界。
- 官方 Base URL 不属于配置 Schema；`NOVAAGENT_QWEN_BASE_URL` 会作为未知环境变量被拒绝。
- Provider 白名单仍严格等于 `qwen` 和 `doubao`，没有自定义 Provider 注册入口。
- `DASHSCOPE_API_KEY` 不进入 `Settings`，只在 Bootstrap 提供的服务端运行时环境快照中解析；该快照支持进程环境和 Git 忽略的本地 `.env` 文件，进程环境变量优先。
- 千问能力声明为纯文本输入输出、可选 usage，不支持原生流式、工具、思考摘要、图片或音频。

### 3.2 稳定模型错误（MOD-02）

实现位置：`src/novaagent/domain/errors.py`

新增并落实以下稳定错误：

- Web 请求和鉴权：`request_invalid`、`request_too_large`、`authentication_required`、`message_too_long`。
- Provider 凭据：`secret_missing`、`provider_authentication_failed`。
- 临时失败：`provider_rate_limited`、`provider_timeout`、`provider_busy`、`provider_unavailable`。
- 非重试失败：`provider_model_invalid`、`provider_input_rejected`。
- 响应契约：`provider_response_invalid`。

错误对象统一携带 `retryable`，协议驱动据此生成错误事件；Web 将错误映射为稳定 HTTP 状态和统一错误信封。上游原始错误正文、异常信息、请求头和密钥不会返回给浏览器。

### 3.3 QwenModelAdapter（MOD-01～MOD-04、ECO-01）

实现位置：`src/novaagent/infrastructure/models/qwen/adapter.py`

已实现：

- 固定调用 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。
- 使用注入的进程级 `httpx.AsyncClient`，不依赖 DashScope SDK或全局 SDK 状态。
- 从启动时解析的 secret provider 读取 `DASHSCOPE_API_KEY`，缺失时在发网前失败；密钥可来自进程环境、项目目录 `.env`、`--env-file` 或 `NOVAAGENT_ENV_FILE` 指定的本地文件。
- 请求固定使用 `stream=false` 和 `enable_thinking=false`。
- 阶段 03 在发网前拒绝工具、tool 消息和非文本 ContentBlock。
- 成功响应只读取 `choices[0].message.content` 和可选 usage。
- `reasoning_content` 和其他隐藏推理字段完全忽略，不形成输出、事件或 Web 内容。
- 上游 `total_tokens` 不受信任；NovaAgent 使用输入和输出 token 相加计算合计。
- 非法 JSON、空 choices、空回答、tool calls 和非法 usage 统一转换为 `provider_response_invalid`。
- 连接失败、429、502、503 和 504 按限制重试；读取或写入超时不重试。
- `Retry-After` 最大遵守 2 秒；并发使用 Semaphore 限制，异常路径通过 `finally` 释放额度。

### 3.4 单轮应用服务和事件投影（WEB-02）

实现位置：`src/novaagent/application/chat/single_turn.py`

已实现：

- 每次调用只创建一条 user Message，不裁剪合法输入的首尾空白。
- 输入上限为 32,000 个 Unicode 字符；空白输入继续复用阶段 02 的 `message_empty`。
- `ModelRequest.messages` 只有当前消息，`tools=()`，请求方不能覆盖模型参数。
- 继续通过 `run_protocol()` 生成统一 AgentEvent，没有建立第二套普通聊天流程。
- 生产 `SingleTurnEventProjection` 只保留 run ID 和可选 usage，不缓存完整事件、输入、回答或思考摘要。
- 使用单调时钟计算非负端到端毫秒耗时。
- 不注入、不读取且不写入 `SessionStorePort`；每次请求生成独立 run 和 message ID。

### 3.5 Web API、安全边界和生命周期（WEB-02、ECO-05）

实现位置：

- `src/novaagent/interfaces/web/app.py`
- `src/novaagent/interfaces/web/chat_protocol.py`
- `src/novaagent/bootstrap/container.py`
- `src/novaagent/application/diagnostics/service.py`

已实现：

- `POST /api/v1/chat`，请求只接受严格的 `message` 字符串字段。
- `application/json`、64 KiB 请求体、未知字段和字段类型均在受控边界校验。
- local 模式直接访问；token 模式接受 `X-NovaAgent-Token` 或 Bearer Token。
- 页面和静态资源公开，聊天与诊断 API 继续受 Web 鉴权保护。
- 成功响应包含协议版本、run ID、阶段 02 Message Schema、Provider、模型、可选 usage 和耗时。
- 失败响应包含稳定错误码、中文提示、request ID、retryable 和可选 field。
- 所有响应增加 CSP、`nosniff`、`no-referrer` 和禁止 framing 的安全头。
- Trusted Host 校验保留阶段 01 的 loopback/Token 绑定边界。
- Bootstrap 为应用装配一个可复用 AsyncClient，在 FastAPI lifespan 结束时关闭。
- 诊断使用与 Adapter 相同的环境快照，只返回密钥是否存在的布尔值。

### 3.6 最小 Web 页面（WEB-04、ECO-05）

实现位置：

- `src/novaagent/interfaces/web/static/index.html`
- `src/novaagent/interfaces/web/static/app.js`
- `src/novaagent/interfaces/web/static/styles.css`

页面包含：

- 单轮范围和不保存会话的明确提示。
- 32,000 字符文本输入、发送、清空和字符计数。
- 等待、成功和错误状态。
- Provider、模型、耗时及输入/输出/合计 token 元信息。
- 千问 API Key “已配置/未配置”状态。
- 与 Provider 密钥明确区分的 Web 访问令牌输入。

安全边界：

- 页面不存在 Provider API Key 输入、保存、编辑或删除控件。
- Web Token 只存在当前 JavaScript 内存，不写 URL、Cookie、`localStorage` 或 `sessionStorage`。
- 回答只通过 `textContent` 写入页面，不使用 `innerHTML`。
- 页面不加载 CDN、外部脚本、字体、Markdown 渲染器或前端框架。

## 4. 测试与验证证据

### 4.1 自动化测试和覆盖率

执行命令：

```text
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache \
uv run pytest --cov=novaagent --cov-report=term-missing -q
```

结果：`155 passed`，项目总覆盖率 `95%`。

阶段 03 关键模块覆盖率：

| 模块 | 覆盖率 |
| --- | ---: |
| `application/chat/single_turn.py` | 100% |
| `infrastructure/models/qwen/adapter.py` | 93% |
| `interfaces/web/app.py` | 98% |
| `interfaces/web/chat_protocol.py` | 100% |
| `bootstrap/container.py` | 100% |
| `config/model.py` | 96% |
| `config/loader.py` | 98% |
| `config/secrets.py` | 96% |

覆盖的关键路径包括：

- 配置默认值、环境覆盖、模型名边界、数值解析、豆包默认拒绝和自定义 Base URL 拒绝。
- 严格单条消息、合法空白保留、空白和超长输入零模型调用、独立 ID、usage 和耗时。
- 固定 URL、Authorization 存在性、`stream=false`、`enable_thinking=false` 和模型参数。
- reasoning 丢弃、usage 可缺失、矛盾 total 忽略、非法 JSON/choices/content/usage/tool calls 拒绝。
- 401/403、408/504、429、400 模型/输入分类、5xx、连接重试、读取超时不重试和 Retry-After 上限。
- 缺少密钥、工具和非文本请求在发网前拒绝，断言出站请求次数为零。
- 本地 `.env` 的注释、`export`、引号、进程环境覆盖、显式文件错误和不支持键校验。
- Web 成功闭环、local/token 鉴权、空白、未知字段、非法 JSON、错误 Content-Type、超长消息和超大 body。
- 统一错误信封、request ID、安全头、密钥诊断布尔值和静态页面公开规则。
- Qwen Adapter 静态满足 ModelPort；Domain/Application 禁止导入 FastAPI、HTTPX 或 DashScope。
- 阶段 01 和阶段 02 的全部回归测试。

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

- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 56 source files`
- Pytest：`155 passed`
- 总覆盖率：`95%`
- Git whitespace 检查：通过

### 4.3 Doctor 回归诊断

执行命令：

```text
NOVAAGENT_DATA_DIR=/private/tmp/novaagent-doctor-data \
NOVAAGENT_LOG_DIR=/private/tmp/novaagent-doctor-logs \
NOVAAGENT_WORKSPACE_DIR=/private/tmp/novaagent-doctor-workspace \
UV_CACHE_DIR=/private/tmp/novaagent-uv-cache \
uv run novaagent doctor --environment test
```

结果：`status: ok`。千问和豆包仍是仅有的启用 Provider；未提供真实密钥时只产生预期 warning，不影响诊断成功，也不泄露密钥值。

## 5. MockTransport 无网络演示

自动化集成演示使用符合 DashScope OpenAI-compatible 形状的假响应：

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "NOVAAGENT_OK",
        "reasoning_content": "must never appear"
      }
    }
  ],
  "usage": {
    "prompt_tokens": 5,
    "completion_tokens": 3,
    "total_tokens": 999
  }
}
```

演示确认：

- 出站 URL 精确等于固定官方 chat completions 地址。
- 请求模型为 `qwen3.8-max`，关闭 stream 和 thinking。
- Web 返回回答 `NOVAAGENT_OK`、Provider `qwen`、模型、run ID 和非负耗时。
- `reasoning_content` 不出现在领域输出、事件或 Web 响应。
- 上游矛盾的 `total_tokens=999` 被忽略，Web 合计为 `5 + 3 = 8`。
- 测试只验证 Authorization 头存在，不快照或打印密钥值。
- 缺少密钥时 MockTransport 调用次数为零。

该演示可离线、确定性重复执行，证明 NovaAgent 内部完整调用链和供应商 HTTP 契约；它不证明真实账号权限、真实模型可用性或当前外部网络状态。

## 6. 设计与实现差异

| 项目 | 设计草图 | 实际实现 | 影响 |
| --- | --- | --- | --- |
| Adapter 模块拆分 | 可拆为 `adapter.py`、`mapper.py`、`retry.py` | Mapper 和短重试策略合并在 `adapter.py` | 设计已允许小型私有函数合并；减少空模块，无产品差异 |
| HTTP 客户端生命周期 | lifespan 创建并关闭进程级客户端 | Bootstrap 构建应用时创建一次，lifespan 关闭 | 仍为单实例连接池且可注入 MockTransport；未创建每请求客户端 |
| 前端框架 | 无框架、无构建工具 | 使用静态 HTML、JavaScript 和 CSS | 符合设计，后续可在稳定 API 上渐进增强 |
| 供应商 request ID 日志 | 允许记录脱敏关联值 | 本阶段没有增加供应商响应日志 | 更保守，不影响用户功能；没有泄露响应正文的风险 |
| 密钥来源 | 原设计为进程环境变量 | 实际支持项目目录 `.env`、`--env-file`、`NOVAAGENT_ENV_FILE` 和进程环境；进程环境优先 | 满足本地配置需求，`.env` 已由 Git 忽略，Web 仍不管理密钥 |
| 端到端测试文件布局 | 设计建议单独的 end-to-end 文件 | 完整闭环集中在 Web integration 测试 | 测试语义和覆盖范围不变，避免重复启动同一测试链 |

除 D03-17 按负责人新增本地 `.env` 配置需求修订外，未发现需要改变 D03-01 ～ D03-16、API 路径、错误码、思考摘要规则或真实验收方式的偏差。

## 7. 安全与产品边界确认

- 没有将真实 `DASHSCOPE_API_KEY` 写入源码、TOML、测试、页面或文档；本地 `.env` 已由 Git 忽略。
- Web 当前和后续均不管理 Provider API Key；页面只读取配置状态布尔值。
- `NOVAAGENT_WEB_TOKEN` 与 Provider 密钥明确分离，只保存在页面内存。
- 官方 Base URL 固定在 Adapter，配置和 Web 均不能建立任意出站地址。
- 默认日志不记录用户完整输入、模型完整回答、HTTP 请求体或供应商响应体。
- `reasoning_content` 被丢弃，不记录、不保存、不进入 AgentEvent 或 Web。
- 用户和模型文本用 `textContent` 展示，不执行 HTML 或脚本。
- 请求体、字符数、超时、重试和并发均有明确上限。
- 无密钥时健康和诊断可用，聊天失败且零出站请求。
- Provider 范围仍只有千问和豆包，本阶段只实例化千问。
- 用户聊天入口仍只有 Web，没有增加 CLI、桌面端或第三方消息通道。

## 8. 真实千问 Web 验收记录

项目负责人于 2026-08-17 使用 Git 忽略的本地 `.env` 完成受控真实验收，并确认：

1. `novaagent doctor --environment local` 返回 `status: ok`，千问 `secret_present: true`；诊断没有显示密钥值。
2. Web 控制台通过真实千问账号成功获得回答。
3. 页面显示 Provider `qwen`、模型 `qwen3.8-max`、耗时和 usage，结果正常。
4. 空白输入被页面正确拦截，没有形成聊天请求。
5. 连续发送仍保持阶段 03 定义的严格单轮语义，没有隐式携带上一轮历史。
6. 页面没有显示原始思维链、`reasoning_content` 或 API Key；Web 只展示密钥配置状态。
7. 未在聊天、源码、文档、测试或 Git 中记录真实密钥、完整问题或完整回答。

该证据补足了 MockTransport 无法证明的真实账号权限、真实模型可用性和实际 Web 调用链。阶段 03 没有剩余验收项。

## 9. 当前验收决策

截至 2026-08-17：

- 设计：已确认。
- 实现：已完成。
- 自动化测试：已完成。
- MockTransport 无网络演示：已完成。
- 真实千问 Web 演示：已完成，项目负责人确认全部检查正常。
- 最终验收：已验收。

阶段结论：**阶段 03 已完成并通过验收**。

阶段 04 的前置条件已经满足，可以进入设计；阶段 04 设计确认前仍不直接开始业务代码实现。
