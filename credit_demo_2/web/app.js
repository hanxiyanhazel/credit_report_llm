function generateUuid() {
  if (typeof crypto !== "undefined") {
    if (typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    if (typeof crypto.getRandomValues === "function") {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0"));
      return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
    }
  }
  return `fallback-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const state = {
  reportType: "individual",
  reports: [],
  selectedReportId: "",
  sessionId: generateUuid(),
  conversations: [],
  currentConvId: "",
  lastMeta: null,
};

const sampleQuestions = [
  "近24个月的逾期账户有多少？",
  "这些账户都是什么分类，分别多少钱？",
  "那近15个月的逾期账户有多少呢？",
  "近6个月逾期次数和逾期金额是多少？",
  "近1年、近2年最多连续逾期期数是多少？",
  "近2年有没有B/D/G这类特殊风险状态？",
  "当前未结清账户有多少个？",
  "当前未结清账户余额合计是多少？",
  "当前未结清贷款借款金额合计是多少？",
  "帮我汇总一下未结清账户数、余额、借款金额三项指标。",
  "未结清贷款分类分布是什么？",
  "贷款总笔数、总金额、总余额是多少？",
  "近1个月查询次数是多少？",
  "近2年查询次数是多少？",
  "近1年、近2年查询次数分别是多少？",
  "最近1个月查询记录概要是什么？",
  "有没有在途异议？",
  "是否存在非正常五级分类？",
  "担保余额是多少？",
  "居住地址和单位地址是否同省市？",
  "通讯地址、户籍地址、居住地址、单位地址分别是什么？",
  "近两年信用卡是否有个性化分期或展期？",
  "信用卡数量、总额度、已用额度、使用率是多少？",
];

function el(id) {
  return document.getElementById(id);
}

function setTopStatus(text, isError = false) {
  const dom = el("topStatus");
  dom.textContent = text || "";
  dom.style.color = isError ? "#dc2626" : "#2563eb";
}

function currentConversation() {
  return state.conversations.find(c => c.id === state.currentConvId);
}

function createConversation(title = "新对话") {
  const conv = { id: generateUuid(), title, messages: [], metas: [] };
  state.conversations.unshift(conv);
  state.currentConvId = conv.id;
}

function renderSamples() {
  const box = el("samples");
  box.innerHTML = "";
  sampleQuestions.forEach(q => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = q;
    btn.onclick = () => {
      const input = el("questionInput");
      input.value = q;
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      setTopStatus("示例问题已放入输入框，请点击“发送”提交。");
    };
    box.appendChild(btn);
  });
}

function renderHistory() {
  const list = el("historyList");
  list.innerHTML = "";
  state.conversations.forEach(conv => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.textContent = conv.title;
    btn.onclick = () => {
      state.currentConvId = conv.id;
      renderMessages();
      const idx = conv.metas.length - 1;
      if (idx >= 0) renderMeta(conv.metas[idx]);
    };
    li.appendChild(btn);
    list.appendChild(li);
  });
}

function renderMessages() {
  const box = el("messages");
  box.innerHTML = "";
  const conv = currentConversation();
  if (!conv) return;
  conv.messages.forEach(m => {
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    div.textContent = m.content;
    box.appendChild(div);
  });
  box.scrollTop = box.scrollHeight;
}

function renderMeta(meta) {
  el("metaAnswerMode").textContent = meta?.answer_mode || "-";
  el("metaQuestionType").textContent = meta?.question_type || "-";
  el("metaConfidence").textContent = meta?.confidence || "-";
  el("metaVerifier").textContent = meta?.verifier_status || "-";
  el("metaReason").textContent = meta?.cannot_answer_reason || "-";
  el("metaEvidence").textContent = JSON.stringify(meta?.evidence_paths || [], null, 2);
  el("metaQueryPlan").textContent = JSON.stringify(meta?.query_plan || {}, null, 2);
  el("metaQueryResult").textContent = JSON.stringify(meta?.query_result || {}, null, 2);
  const trace = meta?.prompt_trace || {};
  el("metaPlannerSystemPrompt").textContent = trace?.planner_system_prompt || "-";
  el("metaPlannerPromptText").textContent = trace?.planner_prompt_text || "-";
  el("metaPlannerOutput").textContent = JSON.stringify(trace?.planner_output || {}, null, 2);
  el("metaAnswerSystemPrompt").textContent = trace?.answer_system_prompt || "-";
  el("metaAnswerPromptText").textContent = trace?.answer_prompt_text || "-";
  el("metaAnswerPayload").textContent = JSON.stringify(trace?.answer_payload || {}, null, 2);
  el("metaPromptTrace").textContent = JSON.stringify(trace, null, 2);
}

async function loadReports() {
  const url = `/api/reports/list?report_type=${encodeURIComponent(state.reportType)}`;
  const resp = await fetch(url);
  const data = await resp.json();
  state.reports = data.reports || [];
  const select = el("reportSelect");
  select.innerHTML = "";
  state.reports.forEach(r => {
    const op = document.createElement("option");
    op.value = r.report_id;
    op.textContent = `${r.customer_name} (${r.report_id}) [${r.status}]`;
    select.appendChild(op);
  });
  if (!state.selectedReportId && state.reports.length > 0) {
    state.selectedReportId = state.reports[0].report_id;
  } else if (state.selectedReportId && state.reports.some(r => r.report_id === state.selectedReportId)) {
    // keep
  } else if (state.reports.length > 0) {
    state.selectedReportId = state.reports[0].report_id;
  }
  select.value = state.selectedReportId || "";
}

async function uploadReport() {
  const xml = el("xmlFile").files[0];
  const pdf = el("pdfFile").files[0];
  if (!xml || !pdf) {
    setTopStatus("请先选择 XML 和 PDF 文件。", true);
    return;
  }
  const fd = new FormData();
  fd.append("report_type", state.reportType);
  fd.append("customer_name", el("customerName").value || "");
  fd.append("xml_file", xml);
  fd.append("pdf_file", pdf);

  setTopStatus("正在上传并解析，请稍候...");
  const resp = await fetch("/api/reports/upload", { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok) {
    setTopStatus(data.detail || data.error || "上传失败", true);
    return;
  }
  state.selectedReportId = data.report_id;
  await loadReports();
  setTopStatus(`上传完成：${data.report_id}，状态=${data.status}`);
}

async function sendQuestion() {
  const input = el("questionInput");
  const q = (input.value || "").trim();
  if (!q) return;
  if (!state.selectedReportId) {
    setTopStatus("请先选择报告。", true);
    return;
  }
  let conv = currentConversation();
  if (!conv) {
    createConversation(q.slice(0, 16) || "新对话");
    conv = currentConversation();
  }
  conv.messages.push({ role: "user", content: q });
  input.value = "";
  renderMessages();

  const payload = {
    session_id: state.sessionId,
    report_id: state.selectedReportId,
    report_type: state.reportType,
    messages: conv.messages.map(m => ({ role: m.role, content: m.content })),
  };

  setTopStatus("模型处理中...");
  const loadingIndex = conv.messages.push({ role: "assistant", content: "大模型加载中..." }) - 1;
  const loadingSteps = [
    "大模型加载中：正在理解问题...",
    "大模型加载中：正在匹配可用证据...",
    "大模型加载中：正在计算并组织答案...",
  ];
  let stepIdx = 0;
  conv.messages[loadingIndex].content = loadingSteps[stepIdx];
  renderMessages();
  const stepTimer = setInterval(() => {
    stepIdx = (stepIdx + 1) % loadingSteps.length;
    conv.messages[loadingIndex].content = loadingSteps[stepIdx];
    renderMessages();
  }, 900);
  el("sendBtn").disabled = true;
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      conv.messages[loadingIndex] = { role: "assistant", content: `请求失败：${data.detail || data.error || "unknown error"}` };
      renderMessages();
      setTopStatus("请求失败", true);
      return;
    }
    conv.messages[loadingIndex] = { role: "assistant", content: data.answer || "" };
    conv.metas.push(data);
    renderMessages();
    renderMeta(data);
    renderHistory();
    setTopStatus("完成");
  } catch (err) {
    conv.messages[loadingIndex] = { role: "assistant", content: `请求失败：${String(err)}` };
    renderMessages();
    setTopStatus("网络错误，请检查后端服务。", true);
  } finally {
    clearInterval(stepTimer);
    el("sendBtn").disabled = false;
  }
}

function bindEvents() {
  el("reportType").onchange = async e => {
    state.reportType = e.target.value;
    if (state.reportType !== "individual") {
      setTopStatus("当前仅支持个人报告。", true);
      return;
    }
    await loadReports();
    setTopStatus("已切换到个人报告");
  };
  el("reportSelect").onchange = e => {
    state.selectedReportId = e.target.value;
    setTopStatus(`当前报告：${state.selectedReportId}`);
  };
  el("uploadBtn").onclick = uploadReport;
  el("sendBtn").onclick = sendQuestion;
  el("questionInput").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuestion();
    }
  });
  el("newChatBtn").onclick = () => {
    createConversation("新对话");
    renderHistory();
    renderMessages();
    renderMeta(null);
  };
}

async function init() {
  renderSamples();
  bindEvents();
  createConversation("新对话");
  renderHistory();
  renderMessages();
  renderMeta(null);
  await loadReports();
  if (state.selectedReportId) {
    setTopStatus(`当前报告：${state.selectedReportId}`);
  }
}

init();
