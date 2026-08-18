"use strict";

const elements = {
  clearSession: document.querySelector("#clear-session"),
  characterCount: document.querySelector("#character-count"),
  deleteSession: document.querySelector("#delete-session"),
  errorCard: document.querySelector("#error-card"),
  errorMessage: document.querySelector("#error-message"),
  errorReference: document.querySelector("#error-reference"),
  message: document.querySelector("#message"),
  messages: document.querySelector("#messages"),
  meta: {
    context: document.querySelector("#meta-context"),
    input: document.querySelector("#meta-input"),
    model: document.querySelector("#meta-model"),
    output: document.querySelector("#meta-output"),
    provider: document.querySelector("#meta-provider"),
    total: document.querySelector("#meta-total"),
  },
  newSession: document.querySelector("#new-session"),
  providerStatus: document.querySelector("#provider-status"),
  refreshStatus: document.querySelector("#refresh-status"),
  requestState: document.querySelector("#request-state"),
  resultCard: document.querySelector("#result-card"),
  send: document.querySelector("#send"),
  sessionList: document.querySelector("#session-list"),
  sessionRevision: document.querySelector("#session-revision"),
  stop: document.querySelector("#stop"),
  tokenPanel: document.querySelector("#token-panel"),
  webToken: document.querySelector("#web-token"),
  title: document.querySelector("#chat-title"),
};

const state = {
  activeRunId: null,
  busy: false,
  session: null,
};

function requestHeaders(json = false) {
  const headers = {};
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  const token = elements.webToken.value;
  if (token) {
    headers["X-NovaAgent-Token"] = token;
  }
  return headers;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

function showError(payload, fallback) {
  const error = payload && payload.error ? payload.error : {};
  elements.errorMessage.textContent = error.message || fallback;
  elements.errorReference.textContent = error.request_id
    ? `请求编号：${error.request_id}`
    : "";
  elements.errorCard.hidden = false;
}

function setBusy(busy) {
  state.busy = busy;
  elements.send.disabled = busy;
  elements.newSession.disabled = busy;
  elements.clearSession.disabled = busy;
  elements.deleteSession.disabled = busy;
  elements.message.disabled = busy;
  elements.stop.disabled = !busy;
  elements.requestState.textContent = busy ? "正在接收千问流式回复…" : "";
}

function renderSessionList(sessions) {
  elements.sessionList.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement("p");
    empty.className = "session-empty";
    empty.textContent = "还没有会话";
    elements.sessionList.append(empty);
    return;
  }
  for (const session of sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    if (state.session && state.session.session_id === session.session_id) {
      button.classList.add("selected");
    }
    const title = document.createElement("strong");
    title.textContent = session.title;
    const detail = document.createElement("span");
    detail.textContent = `${session.message_count} 条消息 · revision ${session.revision}`;
    button.append(title, detail);
    button.addEventListener("click", () => void selectSession(session.session_id));
    elements.sessionList.append(button);
  }
}

function renderMessages(messages) {
  elements.messages.replaceChildren();
  for (const message of messages) {
    const text = message.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("");
    appendMessage(message.role, text, false);
  }
}

function appendMessage(role, text, temporary) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  if (temporary) {
    article.classList.add("temporary");
  }
  const label = document.createElement("p");
  label.className = "message-role";
  label.textContent = role === "user" ? "你" : "千问";
  const content = document.createElement("pre");
  content.className = "message-content";
  content.textContent = text;
  article.append(label, content);
  elements.messages.append(article);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return content;
}

async function refreshDiagnostics() {
  elements.providerStatus.textContent = "正在读取配置…";
  try {
    const response = await fetch("/api/v1/diagnostics", {
      headers: requestHeaders(),
    });
    const payload = await readJson(response);
    if (response.status === 401) {
      elements.tokenPanel.hidden = false;
      elements.providerStatus.textContent = "需要 Web 访问令牌才能读取服务状态";
      return;
    }
    if (!response.ok || !payload) {
      elements.providerStatus.textContent = "暂时无法读取服务状态";
      return;
    }
    elements.tokenPanel.hidden = payload.web.auth_mode !== "token";
    const qwen = payload.providers.details.qwen;
    const secret = qwen.secret_present ? "已配置" : "未配置";
    elements.providerStatus.textContent = `千问 · ${secret} API Key`;
  } catch (_error) {
    elements.providerStatus.textContent = "无法连接 NovaAgent 服务";
  }
}

async function loadSessions() {
  const response = await fetch("/api/v1/sessions", { headers: requestHeaders() });
  const payload = await readJson(response);
  if (!response.ok || !payload) {
    showError(payload, "无法读取会话列表。");
    return [];
  }
  renderSessionList(payload.sessions || []);
  return payload.sessions || [];
}

async function createSession() {
  const response = await fetch("/api/v1/sessions", {
    method: "POST",
    headers: requestHeaders(true),
    body: "{}",
  });
  const payload = await readJson(response);
  if (!response.ok || !payload) {
    showError(payload, "无法创建会话。");
    return;
  }
  await selectSession(payload.session.session_id);
}

async function selectSession(sessionId) {
  if (state.busy) {
    showError(null, "当前会话正在生成，请先停止生成。");
    return;
  }
  const response = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
    headers: requestHeaders(),
  });
  const payload = await readJson(response);
  if (!response.ok || !payload) {
    showError(payload, "无法读取会话。");
    return;
  }
  state.session = payload.session;
  elements.title.textContent = payload.session.title;
  elements.sessionRevision.textContent = `revision ${payload.session.revision}`;
  renderMessages(payload.messages || []);
  elements.errorCard.hidden = true;
  await loadSessions();
}

function parseSseBlock(block) {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");
  if (!data) {
    return null;
  }
  try {
    return JSON.parse(data);
  } catch (_error) {
    return null;
  }
}

async function consumeStream(response, answerContent) {
  if (!response.body) {
    throw new Error("响应不支持流式读取");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = null;
  while (true) {
    const result = await reader.read();
    buffer += decoder.decode(result.value || new Uint8Array(), { stream: !result.done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const event = parseSseBlock(block);
      if (event) {
        terminal = handleAgentEvent(event, answerContent) || terminal;
      }
    }
    if (result.done) {
      break;
    }
  }
  if (buffer.trim()) {
    const event = parseSseBlock(buffer);
    if (event) {
      terminal = handleAgentEvent(event, answerContent) || terminal;
    }
  }
  return terminal;
}

function handleAgentEvent(event, answerContent) {
  if (event.type === "run_started") {
    state.activeRunId = event.run_id;
  } else if (event.type === "context_prepared") {
    elements.meta.context.textContent = `${event.payload.included_messages} 条消息 / ${event.payload.estimated_input_tokens} 估算单位`;
  } else if (event.type === "text_delta") {
    answerContent.textContent += event.payload.delta;
    elements.messages.scrollTop = elements.messages.scrollHeight;
  } else if (event.type === "tool_call") {
    elements.requestState.textContent = `正在调用工具：${event.payload.call.tool_name}`;
  } else if (event.type === "tool_result") {
    elements.requestState.textContent = event.payload.result.status === "success" ? "工具已返回，继续生成…" : "工具返回错误，模型正在处理…";
  } else if (event.type === "run_completed") {
    const usage = event.payload.usage;
    if (usage) {
      elements.meta.input.textContent = usage.input_tokens;
      elements.meta.output.textContent = usage.output_tokens;
      elements.meta.total.textContent = usage.input_tokens + usage.output_tokens;
    }
    elements.resultCard.hidden = false;
    return event;
  } else if (event.type === "error") {
    showError({ error: event.payload }, "模型请求未完成。");
  } else if (event.type === "run_cancelled") {
    answerContent.parentElement.classList.add("temporary");
    elements.requestState.textContent = "本轮已取消，未写入会话历史。";
    return event;
  }
  if (event.type === "run_failed") {
    answerContent.parentElement.classList.add("temporary");
    elements.requestState.textContent = "本轮未完成，未写入会话历史。";
    return event;
  }
  return null;
}

async function sendMessage() {
  if (state.busy || !state.session) {
    return;
  }
  const text = elements.message.value;
  if (!text.trim()) {
    showError({ error: { message: "请输入消息后再发送。" } }, "请输入消息后再发送。");
    return;
  }
  setBusy(true);
  elements.errorCard.hidden = true;
  const userContent = appendMessage("user", text, true);
  const answerContent = appendMessage("assistant", "", true);
  try {
    const response = await fetch(
      `/api/v1/sessions/${encodeURIComponent(state.session.session_id)}/messages:stream`,
      {
        method: "POST",
        headers: { ...requestHeaders(true), Accept: "text/event-stream" },
        body: JSON.stringify({
          message: text,
          expected_revision: state.session.revision,
        }),
      },
    );
    if (!response.ok) {
      const payload = await readJson(response);
      showError(payload, "服务暂时无法完成请求，请稍后重试。");
      userContent.parentElement.classList.add("temporary");
      answerContent.parentElement.classList.add("temporary");
      return;
    }
    const terminal = await consumeStream(response, answerContent);
    if (terminal && terminal.type === "run_completed") {
      const detail = await fetch(
        `/api/v1/sessions/${encodeURIComponent(state.session.session_id)}`,
        { headers: requestHeaders() },
      );
      const payload = await readJson(detail);
      if (detail.ok && payload) {
        state.session = payload.session;
        elements.title.textContent = payload.session.title;
        elements.sessionRevision.textContent = `revision ${payload.session.revision}`;
        renderMessages(payload.messages || []);
        await loadSessions();
      }
    }
  } catch (_error) {
    showError(null, "无法连接 NovaAgent 服务，请检查服务是否正在运行。");
    userContent.parentElement.classList.add("temporary");
    answerContent.parentElement.classList.add("temporary");
  } finally {
    state.activeRunId = null;
    setBusy(false);
  }
}

async function stopGeneration() {
  if (!state.activeRunId) {
    return;
  }
  const runId = state.activeRunId;
  elements.requestState.textContent = "正在停止生成…";
  await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: requestHeaders(),
  });
}

async function clearSession() {
  if (!state.session || state.busy || !window.confirm("清空当前会话历史吗？")) {
    return;
  }
  const response = await fetch(
    `/api/v1/sessions/${encodeURIComponent(state.session.session_id)}/messages?expected_revision=${state.session.revision}`,
    { method: "DELETE", headers: requestHeaders() },
  );
  const payload = await readJson(response);
  if (!response.ok || !payload) {
    showError(payload, "无法清空当前会话。");
    return;
  }
  await selectSession(payload.session.session_id);
}

async function deleteSession() {
  if (!state.session || state.busy || !window.confirm("关闭当前会话吗？")) {
    return;
  }
  const response = await fetch(
    `/api/v1/sessions/${encodeURIComponent(state.session.session_id)}?expected_revision=${state.session.revision}`,
    { method: "DELETE", headers: requestHeaders() },
  );
  if (!response.ok) {
    showError(await readJson(response), "无法关闭当前会话。");
    return;
  }
  state.session = null;
  await createSession();
}

elements.message.addEventListener("input", () => {
  elements.characterCount.textContent = `${elements.message.value.length.toLocaleString()} / 32,000`;
});
elements.message.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    void sendMessage();
  }
});
elements.send.addEventListener("click", () => void sendMessage());
elements.stop.addEventListener("click", () => void stopGeneration());
elements.newSession.addEventListener("click", () => void createSession());
elements.clearSession.addEventListener("click", () => void clearSession());
elements.deleteSession.addEventListener("click", () => void deleteSession());
elements.refreshStatus.addEventListener("click", () => void refreshDiagnostics());
elements.webToken.addEventListener("change", () => void refreshDiagnostics());

async function initialize() {
  await refreshDiagnostics();
  const sessions = await loadSessions();
  if (sessions.length) {
    await selectSession(sessions[0].session_id);
  } else {
    await createSession();
  }
}

void initialize();
