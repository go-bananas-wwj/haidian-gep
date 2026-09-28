import { taskApi } from "./api.js";
import { GepGraph, nodeState } from "./graph.js";
import { renderMap } from "./map.js";

const $ = selector => document.querySelector(selector);
const state = { task:null, nodes:[], snapshotId:null, lastEvent:0, eventTimer:null, supplementKeys:{}, graph:null, selected:null, selectedIndicator:null, selectedDescription:"", drawerMode:null, appendix:null };
let lastDrawerTrigger = null;
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
  const pending = state.nodes.filter(node => node.review_status === "pending_review").length;
  $("#task-state").textContent = `任务 ${graph.task.task_id.slice(0, 8)} · 图版本 ${graph.task.graph_version} · ${pending} 项待审核`;
  $("#graph-summary").textContent = `已建立 3 类、22 项指标；当前 ${pending} 项等待人工审核`;
}
function eventText(event) {
  const labels = { "task.created":"创建任务图", "node.revised":"人工修正数据", "node.approved":"审核通过", "node.returned":"退回重查", "supplement.requested":"请求智能体补充", "supplement.blocked":"智能体补充受阻" };
  return labels[event.type] || event.type;
}
function renderEvents(events) {
  const target = $("#event-list"); target.replaceChildren(); if (!events.length) { target.innerHTML = "<li>暂无新增事件</li>"; return; }
  for (const event of events.slice(-8).reverse()) { const item = document.createElement("li"); item.textContent = `${eventText(event)} · ${new Date(event.created_utc).toLocaleString("zh-CN")}`; target.append(item); }
  state.graph.animatePersisted(events);
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
async function openTask(task) {
  closeDrawer({ restoreFocus:false }); state.task = { task_id:task.task_id }; state.lastEvent = 0; state.selected = null; await reload(); startPolling(); switchPage("prepare"); notice(`已恢复任务 ${task.task_id.slice(0, 8)}。数据图和审核状态来自服务端持久化记录。`);
}

function drawerOpen() { return !$("#drawer-overlay").hidden; }
function showDrawer(trigger) {
  if (!drawerOpen() && trigger instanceof HTMLElement) lastDrawerTrigger = trigger;
  const overlay = $("#drawer-overlay"); const drawer = $("#detail-drawer");
  overlay.hidden = false; drawer.setAttribute("aria-hidden", "false");
  requestAnimationFrame(() => { overlay.classList.add("open"); drawer.classList.add("open"); $("#close-drawer").focus(); });
}
function closeDrawer({ restoreFocus = true } = {}) {
  const overlay = $("#drawer-overlay"); const drawer = $("#detail-drawer");
  if (!overlay || overlay.hidden) return;
  overlay.classList.remove("open"); drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true");
  state.selected = null; state.selectedIndicator = null; state.drawerMode = null;
  setTimeout(() => { if (!drawer.classList.contains("open")) overlay.hidden = true; }, 180);
  if (restoreFocus && lastDrawerTrigger?.isConnected) lastDrawerTrigger.focus();
  lastDrawerTrigger = null;
}
function openIndicatorDrawer(node, description, trigger = document.activeElement) {
  const current = state.nodes.find(item => item.node_id === node.node_id) || node;
  state.selected = current; state.selectedIndicator = current; state.selectedDescription = description || "按核算要素、来源和审核状态组织数据支路。"; state.drawerMode = "indicator";
  $("#drawer-title").textContent = `${current.node_key} · ${current.label}`; $("#drawer-status").textContent = nodeState(current)[0];
  $("#detail-description").textContent = state.selectedDescription; $("#drawer-back").hidden = true;
  $("#drawer-evidence-view").hidden = true; $("#drawer-indicator-view").hidden = false;
  $("#fishbone").replaceChildren(state.graph.renderFishbone(current, state.nodes, input => openEvidenceDrawer(input, current)));
  showDrawer(trigger);
}
function evidenceText(evidence) {
  const explanation = evidence.evidence?.current?.explanation || evidence.evidence?.explanation;
  if (explanation) return explanation;
  if (evidence.value !== null) return `智能体定位到一条候选记录，当前值为 ${evidence.value} ${evidence.unit || ""}。提交前须核对年度、区域和来源定位，再由人工审核。`;
  if (evidence.acquisition_status === "awaiting_agent") return "尚未形成候选值。智能体需要先检索已登记来源；如果来源不存在，请选择人工上传、经批准的估计或暂缓。";
  return "当前节点尚无可审核候选，系统不会把空值自动填为零。";
}
function sourceHtml(source) {
  if (!source || !Object.keys(source).length) return "尚无可核验来源。";
  const sourceId = source.source_id || source.original?.source_id || source.current?.source_id || "未登记来源 ID";
  const file = source.source_file || source.current?.source_file || source.original?.source_file || "来源文件待补充";
  const locator = source.locator || source.current?.locator || source.original?.locator || [source.table_id && `表 ${source.table_id}`, source.printed_page && `印刷页 ${source.printed_page}`].filter(Boolean).join("，") || "定位信息待补充";
  return `<strong>${escape(sourceId)}</strong><br>${escape(file)}<br><span class="muted">定位：${escape(locator)}</span>`;
}
function methodHtml(node) {
  const e = node.evidence || {}; return `适用性：${escape(node.applicability_status)}<br>方法：${escape(e.method_id || "方法卡待人工确认")}<br>标准条款：${escape(e.standard_clause || "待补充")}<br>当前状态：${escape(nodeState(node)[0])}`;
}
async function openEvidenceDrawer(node, parentIndicator = state.selectedIndicator, trigger = document.activeElement) {
  try {
    const evidence = await taskApi.evidence(node.node_id); const [label] = nodeState(evidence);
    state.selected = evidence; state.selectedIndicator = parentIndicator; state.drawerMode = "evidence";
    $("#drawer-title").textContent = `${evidence.node_key} · ${evidence.label}`; $("#drawer-status").textContent = `${label} · 输入版本 ${evidence.version}`;
    $("#evidence-value").textContent = evidence.value === null ? "待补充" : evidence.value; $("#evidence-unit").textContent = evidence.unit || "";
    $("#evidence-explanation").textContent = evidenceText(evidence); $("#source-card").innerHTML = sourceHtml(evidence.evidence); $("#tool-record").textContent = evidence.evidence?.current?.tool_run_id || evidence.evidence?.tool_run || "当前未记录可展示的工具执行；系统只接受带来源定位的候选。"; $("#method-card").innerHTML = methodHtml(evidence);
    const actions = $("#evidence-actions"); actions.replaceChildren();
    if (evidence.review_status === "pending_review") {
      actions.append(reviewButton(evidence, "approved", "审核通过", true), reviewButton(evidence, "returned", "退回重查"));
    }
    if (["awaiting_agent", "agent_failed"].includes(evidence.acquisition_status)) {
      const supplement = document.createElement("button"); supplement.className = "primary"; supplement.textContent = "请求智能体补充"; supplement.onclick = () => requestSupplement(evidence); actions.append(supplement);
    }
    for (const [kind, labelText] of [["upload", "上传材料"], ["estimate", "填写估计依据"], ["defer", "暂缓处理"]]) { const button = document.createElement("button"); button.textContent = labelText; button.onclick = () => openAssist(kind, evidence); actions.append(button); }
    $("#drawer-back").hidden = !parentIndicator; $("#drawer-indicator-view").hidden = true; $("#drawer-evidence-view").hidden = false; showDrawer(trigger);
  } catch (error) { notice(`读取证据失败：${error.message}`); }
}
function reviewButton(evidence, decision, label, primary = false) {
  const button = document.createElement("button"); button.textContent = label; if (primary) button.className = "primary";
  button.onclick = async () => { const note = window.prompt(decision === "approved" ? "填写审核意见" : "填写退回原因"); if (!note) return; try { await taskApi.review(evidence.node_id, { expected_version:evidence.version, decision, note }); closeDrawer(); await reload(); } catch (error) { if (error.status === 409) notice("该节点已被其他操作更新，请重新打开后查看最新版本。"); else notice(`审核未完成：${error.message}`); } }; return button;
}
async function requestSupplement(evidence) {
  try { const idempotencyKey = state.supplementKeys[evidence.node_id] ||= `web-${crypto.randomUUID()}`; const job = await taskApi.supplement(state.task.task_id, { node_id:evidence.node_id, idempotency_key:idempotencyKey }); closeDrawer(); notice(job.status === "blocked" ? `补充请求已记录，但当前无法运行：${job.reason}` : "已提交智能体补充请求；候选形成后仍需审核。"); await reload(); }
  catch (error) { notice(`补充请求失败：${error.message}`); }
}
let assistance = null;
function openAssist(kind, evidence) { assistance = { kind, evidence }; const labels = { upload:["上传材料", "上传后由系统建立带来源定位的候选，仍需人工审核。"], estimate:["填写估计依据", "估计必须说明方法、适用范围、参数来源和不确定性，不能绕过审核。"], defer:["暂缓处理", "暂缓将把此节点保留为正式核算阻断项，不会按零值计算。"] }; $("#assist-title").textContent = labels[kind][0]; $("#assist-copy").textContent = labels[kind][1]; $("#assist-note").value = ""; $("#assist-dialog").showModal(); }
function saveAssist() { const note = $("#assist-note").value.trim(); if (!note) return; $("#assist-dialog").close(); notice(`已记录“${assistance.kind}”待办：需由数据管理员接入对应的上传/估计登记接口后持久化；该节点仍保持审核闸门。`); }
async function refreshReadiness() { if (!state.task) return; try { const report = await taskApi.readiness(state.task.task_id); const card = $("#readiness-card"); card.innerHTML = `<div><p class="eyebrow">当前图版本</p><div class="summary-number">${report.graph_version}</div></div><div><h2>${report.ready_for_snapshot ? "可生成快照" : "当前不能生成正式快照"}</h2><p>${report.blocking_node_count} 个阻断项需要补充、审核或确认适用性。</p></div><div class="blocker-list">${report.blocking_nodes.slice(0, 40).map(item => `<span class="blocker">${escape(item)}</span>`).join("")}</div>`; $("#gate-summary").textContent = report.ready_for_snapshot ? "所有闸门已通过" : `${report.blocking_node_count} 个阻断项`; }
  catch (error) { $("#readiness-card").textContent = `读取失败：${error.message}`; } }
async function freeze() { try { const snapshot = await taskApi.snapshot(state.task.task_id); state.snapshotId = snapshot.snapshot_id; $("#execute-run").disabled = false; notice(`已冻结快照 ${snapshot.snapshot_id.slice(0, 8)}。之后的数据修正将产生新的图版本。`); } catch (error) { notice(`正式核算被阻断：${(error.body?.blocking_nodes || []).join("、") || error.message}`); } }
function renderRun(run, chain) { const calculation = chain.calculation || {}; const card = $("#run-card"); const total = calculation.formal_gep_value_yuan; card.classList.remove("empty"); card.innerHTML = `<p class="eyebrow">运行 ${escape(run.run_id.slice(0, 8))}</p><h2>${run.status === "succeeded" && total !== null ? "正式 GEP 已生成" : "运行已保存，正式总值仍受阻"}</h2><div class="result-grid"><div><p>正式 GEP（元）</p><div class="summary-number">${total === null || total === undefined ? "—" : escape(total)}</div></div><div><p>阻断项</p><div class="blocker-list">${(calculation.blocking_nodes || []).map(item => `<span class="blocker">${escape(item)}</span>`).join("") || "无"}</div></div></div><p>parent_run_id：${escape(chain.parent_run_id || "首次运行")}</p><p>${escape(run.reason || "确定性公式运行已结束。")}</p>`; }
async function executeRun() { try { const run = await taskApi.run({ snapshot_id:state.snapshotId, idempotency_key:`web-${crypto.randomUUID()}` }); renderRun(run, await taskApi.runChain(run.run_id)); notice(run.status === "succeeded" ? "核算完成；请在结果与交付中查看总账。" : "已保存受阻运行与分项记录；系统没有生成不完整总 GEP。"); } catch (error) { notice(`执行失败：${error.message}`); } }
async function loadAppendix() { if (!state.task) return; try { const appendix = await taskApi.appendix(state.task.task_id); state.appendix = appendix; renderMap($("#map-panel"), appendix); $("#ledger-panel").innerHTML = `<h2>区级总账</h2><p>正式 GEP：${appendix.formal_gep_value === null ? "尚未生成" : `${appendix.formal_gep_value} 元`}</p><p class="muted">非空间总账与空间图层分别显示，避免以未验证的栅格代替区级核算。</p>`; const rows = appendix.rows.map(row => `<tr><td>${row.indicator_id}</td><td>${escape(row.label)}</td><td class="${row.status === "blocked" ? "status-blocked" : "status-ready"}">${row.status === "blocked" ? `阻断 ${row.blocking_nodes.length}` : "可运行"}</td><td>${row.input_nodes.length}</td></tr>`).join(""); $("#appendix-panel").innerHTML = `<h2>附录 E：输入完整性</h2><table class="appendix-table"><thead><tr><th>指标</th><th>名称</th><th>状态</th><th>输入数</th></tr></thead><tbody>${rows}</tbody></table>`; } catch (error) { $("#appendix-panel").textContent = `读取附录 E 失败：${error.message}`; } }

$("#task-form").addEventListener("submit", async event => { event.preventDefault(); try { const task = await taskApi.create({ region_code:"110108", year:2024, boundary_version:$("#boundary").value, standard_version:"GB/T 46869-2025", data_version:$("#data-version").value }); await openTask(task); } catch (error) { notice(`创建任务失败：${error.message}`); } });
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
$("#cancel-assist").onclick = () => $("#assist-dialog").close(); $("#confirm-assist").onclick = saveAssist; $("#go-scheme").onclick = () => switchPage("scheme"); $("#readiness").onclick = refreshReadiness; $("#freeze").onclick = freeze; $("#execute-run").onclick = executeRun; $("#appendix-e").onclick = loadAppendix;
state.graph = new GepGraph($("#graph-canvas"), { onNode:openEvidenceDrawer, onDetail:openIndicatorDrawer }); loadTasks();
