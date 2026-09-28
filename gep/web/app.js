import { taskApi } from "./api.js";
import { GepGraph, nodeState } from "./graph.js";
import { renderMap } from "./map.js";
import { nextActionFor } from "./guide.js";

const $ = selector => document.querySelector(selector);
const state = { task:null, nodes:[], snapshotId:null, lastEvent:0, eventTimer:null, graph:null, selected:null, selectedIndicator:null, selectedDescription:"", drawerMode:null, batchPreview:null, individualReviewMode:false, appendix:null };
let lastDrawerTrigger = null;
let drawerRequestVersion = 0;
const notice = text => { $("#notice").textContent = text; };
const escape = value => String(value ?? "").replace(/[&<>"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]));

function switchPage(page) {
  for (const panel of document.querySelectorAll("[data-page-panel]")) panel.hidden = panel.dataset.pagePanel !== page;
  for (const tab of document.querySelectorAll(".step")) tab.classList.toggle("active", tab.dataset.page === page);
  if (page === "scheme") refreshReadiness(); if (page === "delivery") loadAppendix();
}

function taskRow(task) {
  const row = document.createElement("article"); row.className = "task-row";
  row.innerHTML = `<div><strong>海淀区 ${task.year} 年度核算</strong><div class="task-meta">图版本 ${task.graph_version} · ${task.pending_review_count} 项待审核 · ${task.formal_blocker_count} 个正式阻断项</div></div>`;
  const button = document.createElement("button"); button.textContent = "恢复任务"; button.onclick = () => openTask(task); row.append(button); return row;
}
async function loadTasks() {
  try { const { tasks } = await taskApi.tasks(); const list = $("#task-list"); list.replaceChildren(); if (!tasks.length) list.innerHTML = '<span class="muted">尚无保存的任务。</span>'; else tasks.forEach(task => list.append(taskRow(task))); }
  catch (error) { $("#task-list").textContent = `读取任务中心失败：${error.message}`; }
}
function updateHeader(graph) {
  const auto = state.nodes.filter(node => node.review_status === "auto_verified").length;
  const review = state.nodes.filter(node => node.review_status === "pending_review").length;
  const gap = state.nodes.filter(node => node.acquisition_status === "research_complete").length;
  const expert = state.nodes.filter(node => node.acquisition_status === "manual_required").length;
  const failed = state.nodes.filter(node => node.acquisition_status === "agent_failed").length;
  const active = state.nodes.filter(node => ["agent_queued", "agent_running"].includes(node.acquisition_status)).length;
  $("#task-state").textContent = `任务 ${graph.task.task_id.slice(0, 8)} · 图版本 ${graph.task.graph_version} · ${auto} 项自动采用 · ${review} 项建议复核`;
  $("#graph-summary").textContent = `已建立 3 类、22 项指标；${active} 项处理中 · ${auto} 项自动采用 · ${review} 项建议复核 · ${gap} 项等待数据 · ${expert} 项专家介入 · ${failed} 项执行失败`;
  $("#agent-title").textContent = active ? `智能体处理中 · ${active} 项` : "本轮智能体处理已停在审核闸门";
  $("#agent-text").textContent = `${auto} 项已自动采用，${review} 项建议复核，${gap} 项已完成检索并等待数据，${expert} 项需专家判断。`;
  updateNextAction({ active, auto, review, gap, expert, failed });
}
function firstNodeFor(kind) {
  const matches = kind === "exceptions"
    ? node => ["agent_failed", "manual_required"].includes(node.acquisition_status)
    : node => node.acquisition_status === "research_complete";
  return state.nodes.find(node => node.kind !== "indicator" && matches(node)) || state.nodes.find(matches);
}
function openGuidedNode(kind) {
  const node = firstNodeFor(kind); if (!node) return;
  const indicator = node.kind === "indicator" ? node : state.nodes.find(item => item.node_key === node.parent_key);
  if (node.kind === "indicator") openIndicatorDrawer(node, null, $("#next-action-button"));
  else openEvidenceDrawer(node, indicator, $("#next-action-button"));
}
function updateNextAction(summary) {
  const action = nextActionFor(summary); const button = $("#next-action-button");
  $("#next-action-title").textContent = action.title; $("#next-action-copy").textContent = action.copy;
  button.textContent = action.button; button.disabled = action.disabled; button.dataset.action = action.kind;
  button.onclick = () => {
    if (action.kind === "batch") openBatchReview();
    else if (action.kind === "scheme") switchPage("scheme");
    else if (["exceptions", "gaps"].includes(action.kind)) openGuidedNode(action.kind);
  };
  for (const [index, step] of [...$("#guided-steps").children].entries()) {
    step.classList.toggle("done", index + 1 < action.step); step.classList.toggle("current", index + 1 === action.step);
  }
}
function eventText(event) {
  const labels = { "task.created":"创建任务图", "graph.initialized":"核算图已建立", "node.revised":"人工修正数据", "node.approved":"审核通过", "node.returned":"退回重查", "supplement.auto_enqueued":"全量研究已排队", "supplement.queued":"智能体排队中", "supplement.running":"智能体研究中", "candidate.auto_verified":"高可信候选已自动采用", "supplement.candidate_persisted":"候选已生成·建议复核", "research.completed":"自动检索完成·等待数据", "aef.inspected":"AEF 空间资产已检查", "supplement.manual_required":"需要专家介入", "batch_review.completed":"整批确认完成", "supplement.failed":"执行失败", "supplement.stale":"过期结果未采用", "supplement.blocked":"智能体补充受阻" };
  return labels[event.type] || event.type;
}
function renderEvents(events, { animate = true } = {}) {
  const target = $("#event-list"); target.replaceChildren(); if (!events.length) { target.innerHTML = "<li>暂无新增事件</li>"; return; }
  for (const event of events.slice(-8).reverse()) { const item = document.createElement("li"); item.textContent = `${eventText(event)} · ${new Date(event.created_utc).toLocaleString("zh-CN")}`; target.append(item); }
  if (animate) requestAnimationFrame(() => state.graph.animatePersisted(events));
}
async function reload() {
  if (!state.task) return;
  const [graph, snapshots] = await Promise.all([taskApi.graph(state.task.task_id), taskApi.snapshots(state.task.task_id)]);
  state.task = graph.task; state.nodes = graph.nodes; state.snapshotId = snapshots.snapshots[0]?.snapshot_id || null;
  state.graph.loadView(state.task.task_id); state.graph.render(state.nodes); updateHeader(graph);
  $("#freeze").disabled = false; $("#execute-run").disabled = !state.snapshotId;
  if (state.selected && state.drawerMode === "indicator") openIndicatorDrawer(state.selected, state.selectedDescription, null);
  if (state.selected && state.drawerMode === "evidence") openEvidenceDrawer(state.selected, state.selectedIndicator, null);
  await loadTasks(); await loadPackage(graph.task.data_version);
}
async function loadPackage(version) {
  try { const data = await taskApi.dataVersion(version); $("#data-package").hidden = false; $("#accounting-ready").textContent = data.accounting_ready ? "通过" : "未通过"; $("#alphaearth-candidates").textContent = data.alphaearth_candidates?.length ? `${data.alphaearth_candidates.length} 项` : "未提供"; }
  catch (_) { $("#data-package").hidden = false; $("#accounting-ready").textContent = "未登记"; $("#alphaearth-candidates").textContent = "待数据包登记"; }
}
async function pollEvents() {
  if (!state.task) return;
  try { const { events } = await taskApi.events(state.task.task_id, state.lastEvent); if (!events.length) return; state.lastEvent = events.at(-1).sequence; await reload(); renderEvents(events); }
  catch (error) { notice(`事件恢复失败：${error.message}`); }
}
function startPolling() { clearInterval(state.eventTimer); state.eventTimer = setInterval(pollEvents, 5000); pollEvents(); }
async function openTask(task, { playInitial = false } = {}) {
  closeDrawer({ restoreFocus:false }); state.task = { task_id:task.task_id }; state.lastEvent = 0; state.selected = null; state.individualReviewMode = false;
  switchPage("prepare");
  let schedulingError = null; try { await taskApi.autoSupplement(task.task_id); } catch (error) { schedulingError = error; }
  await reload();
  const { events } = await taskApi.events(state.task.task_id, 0); state.lastEvent = events.at(-1)?.sequence || 0; renderEvents(events, { animate:playInitial });
  startPolling(); notice(schedulingError ? `已恢复任务，但自动补充续排失败：${schedulingError.message}` : `${playInitial ? "已创建" : "已恢复"}任务 ${task.task_id.slice(0, 8)}。数据图和审核状态来自服务端持久化记录。`);
}

function drawerOpen() { return !$("#drawer-overlay").hidden; }
function showDrawer(trigger) {
  if (!drawerOpen() && trigger instanceof HTMLElement) lastDrawerTrigger = trigger;
  const overlay = $("#drawer-overlay"); const drawer = $("#detail-drawer");
  overlay.hidden = false; drawer.setAttribute("aria-hidden", "false");
  requestAnimationFrame(() => { overlay.classList.add("open"); drawer.classList.add("open"); $("#close-drawer").focus(); });
  setTimeout(() => state.graph?.layoutEdges(), 190);
}
function closeDrawer({ restoreFocus = true } = {}) {
  const overlay = $("#drawer-overlay"); const drawer = $("#detail-drawer");
  drawerRequestVersion += 1;
  if (!overlay || overlay.hidden) return;
  overlay.classList.remove("open"); drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true");
  state.selected = null; state.selectedIndicator = null; state.drawerMode = null;
  setTimeout(() => { if (!drawer.classList.contains("open")) overlay.hidden = true; }, 180);
  setTimeout(() => state.graph?.layoutEdges(), 190);
  if (restoreFocus && lastDrawerTrigger?.isConnected) lastDrawerTrigger.focus();
  lastDrawerTrigger = null;
}
function openIndicatorDrawer(node, description, trigger = document.activeElement) {
  drawerRequestVersion += 1;
  const current = state.nodes.find(item => item.node_id === node.node_id) || node;
  state.selected = current; state.selectedIndicator = current; state.selectedDescription = description || "按核算要素、来源和审核状态组织数据支路。"; state.drawerMode = "indicator";
  $("#drawer-title").textContent = `${current.node_key} · ${current.label}`; $("#drawer-status").textContent = nodeState(current)[0];
  $("#detail-description").textContent = state.selectedDescription; $("#drawer-back").hidden = true;
  $("#drawer-evidence-view").hidden = true; $("#drawer-indicator-view").hidden = false;
  $("#fishbone").replaceChildren(state.graph.renderFishbone(current, state.nodes, input => openEvidenceDrawer(input, current)));
  showDrawer(trigger);
}
function currentEvidence(node) { return node.evidence?.current || node.evidence || {}; }
function validationText(evidence) {
  const current = currentEvidence(evidence); const tier = current.risk_tier;
  if (tier === "A") return "高可信：字段、区域、年度、单位和证据身份均通过自动校验，已进入整批确认池。";
  if (tier === "B") return `建议复核：${current.risk_reason || current.explanation || "来源可信，但存在代理变量、转换或口径差异。"}`;
  if (tier === "GAP") return current.explanation || "允许的本地、官方和空间工具均已执行，尚未取得可用数值。";
  if (tier === "C") return current.explanation || "存在冲突、权限或方法判断，需要专家介入。";
  if (evidence.value !== null) return "已形成候选值，等待证据风险分级。";
  return "当前节点不会把空白自动解释为零。";
}
function sourceHtml(source) {
  if (!source || !Object.keys(source).length) return "尚无可核验来源。";
  const current = source.current || source; const original = source.original || {};
  const sourceId = current.source_id || original.source_id || "未登记来源 ID";
  const title = current.title || sourceId; const publisher = current.publisher || "";
  const file = current.source_file || original.source_file || "来源文件待补充";
  const locator = current.locator || original.locator || [original.table_id && `表 ${original.table_id}`, original.printed_page && `印刷页 ${original.printed_page}`].filter(Boolean).join("，") || "定位信息待补充";
  const url = current.final_url || current.url; const link = /^https:\/\//.test(url || "") ? `<br><a href="${escape(url)}" target="_blank" rel="noopener">查看官方原文</a>` : "";
  return `<strong>${escape(title)}</strong>${publisher ? `<br>${escape(publisher)}` : ""}<br><span class="muted">${escape(file)}<br>定位：${escape(locator)}</span>${link}`;
}
function methodHtml(node) {
  const e = node.evidence || {}; const original = e.original || e; const current = currentEvidence(node);
  return `风险等级：${escape(current.risk_tier || "待分级")}<br>适用性：${escape(node.applicability_status)}<br>方法：${escape(original.method_id || "方法卡待确认")}<br>标准条款：${escape(original.standard_clause || "待补充")}<br>当前状态：${escape(nodeState(node)[0])}`;
}
function toolRecordText(node) {
  const current = currentEvidence(node); const tools = current.searched_tools || [];
  const lines = [];
  if (tools.length) lines.push(`已执行：${tools.join(" → ")}`);
  if (current.tool_run_id) lines.push(`工具运行：${current.tool_run_id}`);
  if (current.online_status) lines.push(`官方来源在线校验：${current.online_status}`);
  if (current.aef_result && current.aef_result.status !== "not_applicable") {
    const missing = current.aef_result.missing_prerequisites || [];
    lines.push(`AEF 资产检查：${current.aef_result.status}${missing.length ? `；缺少 ${missing.join("、")}` : ""}`);
  }
  return lines.join("\n") || "尚无工具执行记录。";
}
async function openEvidenceDrawer(node, parentIndicator = state.selectedIndicator, trigger = document.activeElement) {
  const requestVersion = ++drawerRequestVersion;
  try {
    const evidence = await taskApi.evidence(node.node_id); const [label] = nodeState(evidence);
    if (requestVersion !== drawerRequestVersion) return;
    state.selected = evidence; state.selectedIndicator = parentIndicator; state.drawerMode = "evidence";
    $("#drawer-title").textContent = `${evidence.node_key} · ${evidence.label}`; $("#drawer-status").textContent = `${label} · 输入版本 ${evidence.version}`;
    $("#evidence-value").textContent = evidence.value === null ? "尚无数值" : evidence.value; $("#evidence-unit").textContent = evidence.unit || "";
    $("#source-card").innerHTML = sourceHtml(evidence.evidence); $("#evidence-validation").textContent = validationText(evidence); $("#tool-record").textContent = toolRecordText(evidence); $("#method-card").innerHTML = methodHtml(evidence);
    const actions = $("#evidence-actions"); actions.replaceChildren();
    if (evidence.review_status === "auto_verified") {
      if (state.individualReviewMode) actions.append(reviewButton(evidence, "approved", "确认采用", true));
      actions.append(reviewButton(evidence, "returned", "标记问题"), assistanceButton("estimate", "人工修正", evidence));
    } else if (evidence.review_status === "pending_review") {
      actions.append(reviewButton(evidence, "approved", "确认采用", true), reviewButton(evidence, "returned", "要求重查"), assistanceButton("estimate", "人工修正", evidence));
    } else if (evidence.acquisition_status === "research_complete") {
      const retry = document.createElement("button"); retry.className = "primary"; retry.textContent = "重新自动检索"; retry.onclick = () => requestSupplement(evidence); actions.append(retry);
    } else if (evidence.acquisition_status === "manual_required") {
      actions.append(assistanceButton("upload", "补充材料", evidence), assistanceButton("estimate", "选择方法或估算", evidence), assistanceButton("defer", "暂缓", evidence));
    }
    if (["awaiting_agent", "agent_failed"].includes(evidence.acquisition_status)) {
      const supplement = document.createElement("button"); supplement.className = "primary"; supplement.textContent = evidence.acquisition_status === "agent_failed" ? "重试执行" : "开始自动检索"; supplement.onclick = () => requestSupplement(evidence); actions.append(supplement);
    }
    $("#drawer-back").hidden = !parentIndicator; $("#drawer-indicator-view").hidden = true; $("#drawer-evidence-view").hidden = false; showDrawer(trigger);
  } catch (error) { if (requestVersion === drawerRequestVersion) notice(`读取证据失败：${error.message}`); }
}
function reviewButton(evidence, decision, label, primary = false) {
  const button = document.createElement("button"); button.textContent = label; if (primary) button.className = "primary";
  button.onclick = async () => { const note = window.prompt(decision === "approved" ? "填写审核意见" : "填写退回原因"); if (!note) return; try { await taskApi.review(evidence.node_id, { expected_version:evidence.version, decision, note }); closeDrawer(); await reload(); } catch (error) { if (error.status === 409) notice("该节点已被其他操作更新，请重新打开后查看最新版本。"); else notice(`审核未完成：${error.message}`); } }; return button;
}
function assistanceButton(kind, label, evidence) {
  const button = document.createElement("button"); button.textContent = label; button.onclick = () => openAssist(kind, evidence); return button;
}
async function requestSupplement(evidence) {
  try { const idempotencyKey = `web-${crypto.randomUUID()}`; const job = await taskApi.supplement(state.task.task_id, { node_id:evidence.node_id, idempotency_key:idempotencyKey }); closeDrawer(); notice(job.status === "blocked" ? `检索请求已记录，但当前无法运行：${job.reason}` : "已提交自动研究任务；完成后将按证据风险自动分流。"); await reload(); }
  catch (error) { notice(`补充请求失败：${error.message}`); }
}
let assistance = null;
function openAssist(kind, evidence) { assistance = { kind, evidence }; const labels = { upload:["上传材料", "上传后由系统建立带来源定位的候选，仍需人工审核。"], estimate:["填写估计依据", "估计必须说明方法、适用范围、参数来源和不确定性，不能绕过审核。"], defer:["暂缓处理", "暂缓将把此节点保留为正式核算阻断项，不会按零值计算。"] }; $("#assist-title").textContent = labels[kind][0]; $("#assist-copy").textContent = labels[kind][1]; $("#assist-note").value = ""; $("#assist-dialog").showModal(); }
function saveAssist() { const note = $("#assist-note").value.trim(); if (!note) return; $("#assist-dialog").close(); notice(`已记录“${assistance.kind}”待办：需由数据管理员接入对应的上传/估计登记接口后持久化；该节点仍保持审核闸门。`); }
async function openBatchReview() {
  if (!state.task) return;
  try {
    const preview = await taskApi.batchPreview(state.task.task_id); state.batchPreview = preview;
    $("#batch-unreviewed-count").textContent = preview.reviewable_count;
    $("#batch-review-summary").innerHTML = `<div><strong>${preview.auto_ready_count}</strong><span>自动采用</span></div><div><strong>${preview.review_ready_count}</strong><span>建议复核</span></div><div><strong>${preview.hard_blocker_count}</strong><span>保持阻断</span></div>`;
    $("#batch-review-dialog").showModal();
  } catch (error) { notice(`读取整批确认失败：${error.message}`); }
}
async function submitBatchReview(ignore) {
  if (!state.task || !state.batchPreview) return;
  try {
    const result = await taskApi.batchReview(state.task.task_id, {
      expected_graph_version:state.batchPreview.graph_version,
      ignore_individual_review:ignore,
      note:ignore ? "整批确认自动核验与待复核候选" : "取消整批确认，改为逐项审核",
    });
    $("#batch-review-dialog").close();
    if (ignore) {
      state.individualReviewMode = false; notice(`已整批确认 ${result.approved_count} 项；${result.hard_blocker_nodes.length} 个硬阻断保持不变。`); await reload();
    } else {
      state.individualReviewMode = true; notice(`已保留 ${result.reviewable_count} 项逐项审核。`);
      const firstKey = result.review_queue[0]; const first = state.nodes.find(node => node.node_key === firstKey); if (first) openEvidenceDrawer(first);
    }
  } catch (error) { notice(error.status === 409 ? "图版本已变化，请重新打开整批确认。" : `整批确认失败：${error.message}`); }
}
async function refreshReadiness() { if (!state.task) return; try { const report = await taskApi.readiness(state.task.task_id); const card = $("#readiness-card"); card.innerHTML = `<div><p class="eyebrow">当前图版本</p><div class="summary-number">${report.graph_version}</div></div><div><h2>${report.ready_for_snapshot ? "可生成快照" : "当前不能生成正式快照"}</h2><p>${report.blocking_node_count} 个阻断项需要补充、审核或确认适用性。</p></div><div class="blocker-list">${report.blocking_nodes.slice(0, 40).map(item => `<span class="blocker">${escape(item)}</span>`).join("")}</div>`; $("#gate-summary").textContent = report.ready_for_snapshot ? "所有闸门已通过" : `${report.blocking_node_count} 个阻断项`; }
  catch (error) { $("#readiness-card").textContent = `读取失败：${error.message}`; } }
async function freeze() { try { const snapshot = await taskApi.snapshot(state.task.task_id); state.snapshotId = snapshot.snapshot_id; $("#execute-run").disabled = false; notice(`已冻结快照 ${snapshot.snapshot_id.slice(0, 8)}。之后的数据修正将产生新的图版本。`); } catch (error) { notice(`正式核算被阻断：${(error.body?.blocking_nodes || []).join("、") || error.message}`); } }
function renderRun(run, chain) { const calculation = chain.calculation || {}; const card = $("#run-card"); const total = calculation.formal_gep_value_yuan; card.classList.remove("empty"); card.innerHTML = `<p class="eyebrow">运行 ${escape(run.run_id.slice(0, 8))}</p><h2>${run.status === "succeeded" && total !== null ? "正式 GEP 已生成" : "运行已保存，正式总值仍受阻"}</h2><div class="result-grid"><div><p>正式 GEP（元）</p><div class="summary-number">${total === null || total === undefined ? "—" : escape(total)}</div></div><div><p>阻断项</p><div class="blocker-list">${(calculation.blocking_nodes || []).map(item => `<span class="blocker">${escape(item)}</span>`).join("") || "无"}</div></div></div><p>parent_run_id：${escape(chain.parent_run_id || "首次运行")}</p><p>${escape(run.reason || "确定性公式运行已结束。")}</p>`; }
async function executeRun() { try { const run = await taskApi.run({ snapshot_id:state.snapshotId, idempotency_key:`web-${crypto.randomUUID()}` }); renderRun(run, await taskApi.runChain(run.run_id)); notice(run.status === "succeeded" ? "核算完成；请在结果与交付中查看总账。" : "已保存受阻运行与分项记录；系统没有生成不完整总 GEP。"); } catch (error) { notice(`执行失败：${error.message}`); } }
async function loadAppendix() { if (!state.task) return; try { const appendix = await taskApi.appendix(state.task.task_id); state.appendix = appendix; renderMap($("#map-panel"), appendix); $("#ledger-panel").innerHTML = `<h2>区级总账</h2><p>正式 GEP：${appendix.formal_gep_value === null ? "尚未生成" : `${appendix.formal_gep_value} 元`}</p><p class="muted">非空间总账与空间图层分别显示，避免以未验证的栅格代替区级核算。</p>`; const rows = appendix.rows.map(row => `<tr><td>${row.indicator_id}</td><td>${escape(row.label)}</td><td class="${row.status === "blocked" ? "status-blocked" : "status-ready"}">${row.status === "blocked" ? `阻断 ${row.blocking_nodes.length}` : "可运行"}</td><td>${row.input_nodes.length}</td></tr>`).join(""); $("#appendix-panel").innerHTML = `<h2>附录 E：输入完整性</h2><table class="appendix-table"><thead><tr><th>指标</th><th>名称</th><th>状态</th><th>输入数</th></tr></thead><tbody>${rows}</tbody></table>`; } catch (error) { $("#appendix-panel").textContent = `读取附录 E 失败：${error.message}`; } }

$("#task-form").addEventListener("submit", async event => { event.preventDefault(); try { const task = await taskApi.create({ region_code:"110108", year:2024, boundary_version:$("#boundary").value, standard_version:"GB/T 46869-2025", data_version:$("#data-version").value }); await openTask(task, { playInitial:true }); } catch (error) { notice(`创建任务失败：${error.message}`); } });
for (const button of document.querySelectorAll(".step")) button.onclick = () => switchPage(button.dataset.page);
$("#zoom-in").onclick = () => { state.graph.setZoom(.1); $("#zoom-value").textContent = `${Math.round(state.graph.zoom * 100)}%`; }; $("#zoom-out").onclick = () => { state.graph.setZoom(-.1); $("#zoom-value").textContent = `${Math.round(state.graph.zoom * 100)}%`; }; $("#collapse-all").onclick = () => state.graph.setCollapsed(true); $("#expand-all").onclick = () => state.graph.setCollapsed(false);
$("#close-drawer").onclick = () => closeDrawer(); $("#drawer-overlay").onclick = event => { if (event.target === $("#drawer-overlay")) closeDrawer(); }; $("#drawer-back").onclick = () => { if (state.selectedIndicator) openIndicatorDrawer(state.selectedIndicator, state.selectedDescription, null); };
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && drawerOpen()) { closeDrawer(); return; }
  if (event.key !== "Tab" || !drawerOpen()) return;
  const focusable = [...$("#detail-drawer").querySelectorAll('button:not([hidden]):not(:disabled),a[href],input,textarea,[tabindex]:not([tabindex="-1"])')].filter(element => element.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
$("#cancel-assist").onclick = () => $("#assist-dialog").close(); $("#confirm-assist").onclick = saveAssist;
$("#batch-review").onclick = openBatchReview; $("#close-batch-review").onclick = () => $("#batch-review-dialog").close();
$("#confirm-batch-review").onclick = () => submitBatchReview(true); $("#cancel-batch-review").onclick = () => submitBatchReview(false);
$("#go-scheme").onclick = () => switchPage("scheme"); $("#readiness").onclick = refreshReadiness; $("#freeze").onclick = freeze; $("#execute-run").onclick = executeRun; $("#appendix-e").onclick = loadAppendix;
state.graph = new GepGraph($("#graph-canvas"), { onNode:openEvidenceDrawer, onDetail:openIndicatorDrawer }); loadTasks();
