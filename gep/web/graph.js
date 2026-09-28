const CATEGORIES = [
  ["material", "物质产品", "7 个科目"], ["regulating", "调节服务", "12 个科目"], ["cultural", "文化服务", "3 个科目"],
];
const SVG_NS = "http://www.w3.org/2000/svg";
const FLOW_EVENTS = new Set([
  "graph.initialized", "supplement.queued", "supplement.running", "supplement.candidate_persisted",
  "candidate.auto_verified", "research.completed", "aef.inspected", "supplement.manual_required",
  "supplement.failed", "supplement.stale", "batch_review.completed",
]);

// The graph is fixed by GB/T 46869-2025.  Server nodes supply current state,
// values and evidence; this catalogue supplies only the stable visual hierarchy.
export const INDICATORS = [
  ["P1", "农产品", "material"], ["P2", "林产品", "material"], ["P3", "牧产品", "material"], ["P4", "渔产品", "material"], ["P5", "淡水资源", "material"], ["P6", "生态能源", "material"], ["P7", "其他物质产品", "material"],
  ["R1", "水源涵养", "regulating"], ["R2", "土壤保持", "regulating"], ["R3", "防风固沙", "regulating"], ["R4", "海岸防护", "regulating"], ["R5", "洪水调蓄", "regulating"], ["R6", "固碳", "regulating"], ["R7", "氧气提供", "regulating"], ["R8", "空气净化", "regulating"], ["R9", "水净化", "regulating"], ["R10", "局部气候调节", "regulating"], ["R11", "噪声消减", "regulating"], ["R12", "作物授粉", "regulating"],
  ["C1", "旅游康养", "cultural"], ["C2", "休闲游憩", "cultural"], ["C3", "景观增值", "cultural"],
];

const detailDescriptions = {
  P1: "农产品从统计表中的产品清单出发，按产品—产量、价格、成本等核算要素—可定位来源组织为鱼骨图。",
  P2: "林产品按采伐、抚育、果实、苗木等实际经营记录建立产品目录；没有 2024 年经营记录时保持待补充。",
  P3: "牧产品以辖区内实际生产和权属为前提，避免把区外购入产品计入生态产品。",
  P4: "渔产品需要水体、捕捞或养殖产量、当地来源和成本凭据；教学数值不能替代正式输入。",
};

const FIELD_LABELS = {
  "玉米产量": "玉米产量",
  quantity: "产量", harvest_quantity: "采收量", eligible_quantity: "适格产量", deliverable_quantity: "可交付量",
  producer_price: "生产者价格", production_cost: "生产成本", intermediate_cost: "中间投入成本", labor: "劳动报酬",
  depreciation: "固定资产折旧", tax_net: "生产税净额", capital_return: "资本回报", actual_energy_output: "实际能源产出",
  actual_use: "实际使用量", local_used_water: "本地生态供水量", outside_water: "区域外调入水量", recycled_water: "再生水量",
  ecosystem_area: "生态系统面积", area: "核算面积", precipitation: "降水量", surface_runoff: "地表径流量", actual_et: "实际蒸散发量",
  valuation_parameter: "价值参数", npp_or_nep: "NPP / NEP", respiration_or_conversion: "呼吸或转换参数", carbon_price: "碳价",
  pollutant_concentration: "污染物浓度", emission_inventory: "排放清单", removal_parameter: "净化参数", treatment_cost: "治理成本",
  visitor_count: "访问人次", stay_duration: "停留时长", hourly_wage: "小时工资", attribution: "生态归因比例",
};

function readableField(node) {
  return FIELD_LABELS[node.label] || FIELD_LABELS[node.node_key.split(".").at(-1)] || node.label;
}

export function nodeState(node) {
  if (node.review_status === "approved") return ["审核通过", "approved"];
  if (node.review_status === "returned") return ["退回重查", "returned"];
  if (node.review_status === "auto_verified") return ["已自动采用·待整批确认", "auto"];
  if (node.review_status === "pending_review" && node.evidence?.corrections?.length) return ["人工已修正·待审核", "review"];
  if (node.review_status === "pending_review") return ["已补充·建议复核", "review"];
  if (node.acquisition_status === "agent_queued") return ["智能体排队中", "queued"];
  if (node.acquisition_status === "agent_running") return ["智能体补充中", "running"];
  if (node.acquisition_status === "research_complete") return ["已自动检索·等待数据", "gap"];
  if (node.acquisition_status === "manual_required") return ["需专家介入", "manual"];
  if (node.acquisition_status === "agent_failed") return ["执行失败·可重试", "failed"];
  if (node.acquisition_status === "awaiting_agent") return ["待智能体补充", "waiting"];
  return ["需专家介入", "manual"];
}

export class GepGraph {
  constructor(container, { onNode, onDetail } = {}) {
    this.container = container; this.onNode = onNode; this.onDetail = onDetail;
    this.zoom = 1; this.collapsed = {}; this.nodes = []; this.taskId = null; this.edgeLayer = null; this.stage = null;
    this.resizeTimer = null; this.edgeTimers = new Map();
    window.addEventListener("resize", () => { clearTimeout(this.resizeTimer); this.resizeTimer = setTimeout(() => this.layoutEdges(), 100); });
  }
  storageKey() { return this.taskId ? `haidian-gep:view-layout:${this.taskId}` : ""; }
  loadView(taskId) {
    this.taskId = taskId;
    try { const view = JSON.parse(localStorage.getItem(this.storageKey()) || "{}"); this.zoom = Math.max(.65, Math.min(1.45, view.zoom || 1)); this.collapsed = view.collapsed || {}; } catch (_) { this.zoom = 1; this.collapsed = {}; }
  }
  saveView() { if (this.storageKey()) localStorage.setItem(this.storageKey(), JSON.stringify({ zoom: this.zoom, collapsed: this.collapsed })); }
  setZoom(change) { this.zoom = Math.max(.65, Math.min(1.45, Math.round((this.zoom + change) * 100) / 100)); this.saveView(); this.render(); }
  setCollapsed(all) { for (const [key] of CATEGORIES) this.collapsed[key] = all; this.saveView(); this.render(); }
  render(nodes = this.nodes) {
    this.nodes = nodes; const byKey = new Map(nodes.map(node => [node.node_key, node]));
    const stage = document.createElement("div"); stage.className = "graph-stage";
    const edgeLayer = document.createElementNS(SVG_NS, "svg"); edgeLayer.classList.add("edge-layer"); edgeLayer.setAttribute("aria-hidden", "true");
    const scale = document.createElement("div"); scale.className = "graph-scale"; scale.style.transform = `scale(${this.zoom})`;
    const root = document.createElement("div"); root.className = "graph-root";
    root.innerHTML = '<span class="root-node" data-node="root"><strong>GEP 年度核算</strong><small>物质产品 + 调节服务 + 文化服务</small></span>'; scale.append(root);
    const grid = document.createElement("div"); grid.className = "category-grid";
    for (const [category, title, count] of CATEGORIES) {
      const card = document.createElement("section"); card.className = "category";
      const head = document.createElement("div"); head.className = "category-head"; head.dataset.category = category;
      const fold = document.createElement("button"); fold.textContent = this.collapsed[category] ? "展开" : "折叠"; fold.onclick = () => { this.collapsed[category] = !this.collapsed[category]; this.saveView(); this.render(); };
      const titleNode = document.createElement("span"); titleNode.textContent = title;
      const countNode = document.createElement("small"); countNode.textContent = count;
      const controls = document.createElement("span"); controls.className = "category-controls"; controls.append(countNode, fold);
      head.append(titleNode, controls); card.append(head);
      if (!this.collapsed[category]) {
        const stack = document.createElement("div"); stack.className = "indicator-stack";
        for (const [key, label, group] of INDICATORS.filter(row => row[2] === category)) {
          const node = byKey.get(key) || { node_key:key, label, acquisition_status:"awaiting_agent", review_status:"unsubmitted" };
          const [state, style] = nodeState(node); const button = document.createElement("button"); button.className = "graph-node"; button.dataset.node = key;
          button.innerHTML = `<span class="node-name"><span class="node-code">${key}</span>${label}</span><span class="node-state ${style}">${state}</span>`;
          button.onclick = () => this.onDetail?.(node, detailDescriptions[key] || `${label}按方法卡展开必需输入、数据来源和风险状态。`);
          stack.append(button);
        }
        card.append(stack);
      }
      grid.append(card);
    }
    scale.append(grid); stage.append(edgeLayer, scale); this.container.replaceChildren(stage);
    this.stage = stage; this.edgeLayer = edgeLayer; requestAnimationFrame(() => this.layoutEdges());
  }
  layoutEdges() {
    if (!this.stage || !this.edgeLayer) return;
    const stageRect = this.stage.getBoundingClientRect();
    const point = (element, side) => {
      const rect = element.getBoundingClientRect();
      return { x:rect.left - stageRect.left + rect.width / 2, y:(side === "top" ? rect.top : rect.bottom) - stageRect.top };
    };
    const root = this.stage.querySelector('[data-node="root"]'); if (!root) return;
    const paths = [];
    const addPath = (id, start, end) => {
      const path = document.createElementNS(SVG_NS, "path"); const middle = start.y + Math.max(18, (end.y - start.y) * .45);
      path.classList.add("edge-path"); path.dataset.edge = id;
      path.style.setProperty("--flow-delay", `${-(paths.length * .11)}s`);
      path.setAttribute("d", `M ${start.x} ${start.y} C ${start.x} ${middle}, ${end.x} ${middle}, ${end.x} ${end.y}`); paths.push(path);
    };
    for (const [category] of CATEGORIES) {
      const head = this.stage.querySelector(`[data-category="${category}"]`); if (!head) continue;
      addPath(`root:${category}`, point(root, "bottom"), point(head, "top"));
      for (const [key, , group] of INDICATORS.filter(row => row[2] === category)) {
        const indicator = this.stage.querySelector(`[data-node="${key}"]`); if (!indicator) continue;
        addPath(`${category}:${key}`, point(head, "bottom"), point(indicator, "top"));
      }
    }
    const width = Math.max(this.stage.scrollWidth, this.container.clientWidth); const height = Math.max(this.stage.scrollHeight, this.container.clientHeight);
    this.edgeLayer.setAttribute("viewBox", `0 0 ${width} ${height}`); this.edgeLayer.setAttribute("width", width); this.edgeLayer.setAttribute("height", height);
    this.edgeLayer.replaceChildren(...paths);
  }
  animatePersisted(events) {
    const edgeIds = new Set();
    for (const event of events) {
      if (!FLOW_EVENTS.has(event.type)) continue;
      if (event.type === "graph.initialized") { for (const [category] of CATEGORIES) edgeIds.add(`root:${category}`); continue; }
      if (!event.node_id) continue;
      const node = this.nodes.find(item => item.node_id === event.node_id); if (!node) continue;
      const indicatorKey = node.kind === "indicator" ? node.node_key : node.parent_key;
      const indicator = INDICATORS.find(([key]) => key === indicatorKey); if (!indicator) continue;
      edgeIds.add(`${indicator[2]}:${indicatorKey}`);
      const element = this.container.querySelector(`[data-node="${indicatorKey}"]`);
      if (element) { element.classList.remove("node-flow"); requestAnimationFrame(() => element.classList.add("node-flow")); }
    }
    for (const edgeId of edgeIds) {
      const edge = this.edgeLayer?.querySelector(`[data-edge="${edgeId}"]`); if (!edge) continue;
      edge.classList.add("flowing");
      clearTimeout(this.edgeTimers.get(edgeId));
      this.edgeTimers.set(edgeId, setTimeout(() => { edge.classList.remove("flowing"); this.edgeTimers.delete(edgeId); }, 1500));
    }
  }
  // 产品详情以可折叠的鱼骨式树呈现：对象目录 → 具体产品 → 可审核字段。
  renderFishbone(indicator, nodes, onNode) {
    const inputs = nodes.filter(node => node.parent_key === indicator.node_key);
    const tree = document.createElement("div"); tree.className = "product-tree";
    const catalog = document.createElement("div"); catalog.className = "product-catalog";
    catalog.innerHTML = indicator.node_key === "P1" ? '<strong>粮食作物</strong><span>目录由统计表生成</span>' : `<strong>${indicator.label}对象目录</strong><span>待智能体补充并审核</span>`;
    tree.append(catalog);
    const appendProduct = (name, hint, fields) => {
      const product = document.createElement("section"); product.className = "product-branch";
      product.innerHTML = `<header><strong>${name}</strong><span>${hint}</span></header>`;
      const rows = document.createElement("div"); rows.className = "product-fields";
      for (const [label, candidates] of fields) {
        const input = candidates.find(Boolean);
        const row = document.createElement(input ? "button" : "div"); row.className = "product-field";
        if (!input) { row.innerHTML = `<strong>${label}</strong><span class="node-state">待智能体补充</span>`; }
        else { const [status, style] = nodeState(input); row.innerHTML = `<strong>${label}</strong><span>${input.value === null ? "" : `${input.value} ${input.unit || ""}`}</span><span class="node-state ${style}">${status}</span>`; row.onclick = () => onNode(input); }
        rows.append(row);
      }
      product.append(rows); tree.append(product);
    };
    if (indicator.node_key === "P1") {
      const field = key => inputs.find(item => item.node_key.endsWith(`.${key}`));
      appendProduct("玉米", "已从年鉴记录识别", [
        ["产量", [field("quantity")]], ["生产者价格", [field("producer_price")]],
        ["投入与成本", [field("intermediate_cost"), field("labor"), field("depreciation"), field("tax_net"), field("capital_return")]],
      ]);
      appendProduct("小麦（候选）", "候选目录，尚未形成 2024 年可审核记录", [["产量", []], ["生产者价格", []], ["投入与成本", []]]);
      appendProduct("其他粮食（候选）", "候选目录，尚未形成 2024 年可审核记录", [["产量", []], ["生产者价格", []], ["投入与成本", []]]);
    } else if (inputs.length) {
      appendProduct(`${indicator.label} · 待确认对象`, "先确认对象目录与本地归属", inputs.map(input => [readableField(input), [input]]));
    } else {
      tree.innerHTML += '<div class="fish-empty">尚未建立可审核对象目录；此科目保持为待补充，不能按零值计算。</div>';
    }
    return tree;
  }
}
