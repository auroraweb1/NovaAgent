"use strict";

const elements = {
  answer: document.querySelector("#answer"),
  characterCount: document.querySelector("#character-count"),
  clear: document.querySelector("#clear"),
  errorCard: document.querySelector("#error-card"),
  errorMessage: document.querySelector("#error-message"),
  errorReference: document.querySelector("#error-reference"),
  message: document.querySelector("#message"),
  providerStatus: document.querySelector("#provider-status"),
  refreshStatus: document.querySelector("#refresh-status"),
  requestState: document.querySelector("#request-state"),
  resultCard: document.querySelector("#result-card"),
  send: document.querySelector("#send"),
  tokenPanel: document.querySelector("#token-panel"),
  webToken: document.querySelector("#web-token"),
  meta: {
    provider: document.querySelector("#meta-provider"),
    model: document.querySelector("#meta-model"),
    latency: document.querySelector("#meta-latency"),
    input: document.querySelector("#meta-input"),
    output: document.querySelector("#meta-output"),
    total: document.querySelector("#meta-total"),
  },
};

function requestHeaders() {
  const headers = { "Content-Type": "application/json" };
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
  elements.resultCard.hidden = true;
}

function setBusy(busy) {
  elements.send.disabled = busy;
  elements.clear.disabled = busy;
  elements.message.disabled = busy;
  elements.requestState.textContent = busy ? "正在等待千问回复…" : "";
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

async function sendMessage() {
  setBusy(true);
  elements.errorCard.hidden = true;
  elements.resultCard.hidden = true;
  try {
    const response = await fetch("/api/v1/chat", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ message: elements.message.value }),
    });
    const payload = await readJson(response);
    if (!response.ok || !payload) {
      if (response.status === 401) {
        elements.tokenPanel.hidden = false;
      }
      showError(payload, "服务暂时无法完成请求，请稍后重试。");
      return;
    }

    const block = payload.message.content.find((item) => item.type === "text");
    elements.answer.textContent = block ? block.text : "";
    elements.meta.provider.textContent = payload.provider.name;
    elements.meta.model.textContent = payload.provider.model;
    elements.meta.latency.textContent = `${payload.latency_ms} ms`;
    elements.meta.input.textContent = payload.usage ? payload.usage.input_tokens : "—";
    elements.meta.output.textContent = payload.usage ? payload.usage.output_tokens : "—";
    elements.meta.total.textContent = payload.usage ? payload.usage.total_tokens : "—";
    elements.resultCard.hidden = false;
  } catch (_error) {
    showError(null, "无法连接 NovaAgent 服务，请检查服务是否正在运行。");
  } finally {
    setBusy(false);
  }
}

function clearPage() {
  elements.message.value = "";
  elements.characterCount.textContent = "0 / 32,000";
  elements.resultCard.hidden = true;
  elements.errorCard.hidden = true;
  elements.requestState.textContent = "";
  elements.message.focus();
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
elements.clear.addEventListener("click", clearPage);
elements.refreshStatus.addEventListener("click", () => void refreshDiagnostics());
elements.webToken.addEventListener("change", () => void refreshDiagnostics());

void refreshDiagnostics();
