const CATEGORIES = [
  ["material", "物质产品"], ["regulating", "调节服务"], ["cultural", "文化服务"],
];

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

export function nodeState(node) {
  if (node.review_status === "approved") return ["审核通过", "approved"];
  if (node.review_status === "pending_review") return ["智能体已补充·待审核", ""];
  if (node.acquisition_status === "agent_running" || node.acquisition_status === "agent_queued") return ["智能体补充中", "running"];
  if (node.acquisition_status === "returned") return ["退回重查", ""];
  if (node.acquisition_status === "awaiting_agent") return ["待智能体补充", ""];
  return ["待人工协助", ""];
}

export class GepGraph {
  constructor(container, { onNode, onDetail } = {}) {
    this.container = container; this.onNode = onNode; this.onDetail = onDetail;
    this.zoom = 1; this.collapsed = {}; this.nodes = []; this.taskId = null;
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
    const scale = document.createElement("div"); scale.className = "graph-scale"; scale.style.transform = `scale(${this.zoom})`;
    const root = document.createElement("div"); root.className = "graph-root"; root.innerHTML = '<span class="root-node">海淀区 2024 年度 GEP</span>'; scale.append(root);
    const grid = document.createElement("div"); grid.className = "category-grid";
    for (const [category, title] of CATEGORIES) {
      const card = document.createElement("section"); card.className = "category";
      const head = document.createElement("div"); head.className = "category-head";
      const fold = document.createElement("button"); fold.textContent = this.collapsed[category] ? "展开" : "折叠"; fold.onclick = () => { this.collapsed[category] = !this.collapsed[category]; this.saveView(); this.render(); };
      head.append(Object.assign(document.createElement("span"), { textContent: title }), fold); card.append(head);
      if (!this.collapsed[category]) {
        const stack = document.createElement("div"); stack.className = "indicator-stack";
        for (const [key, label, group] of INDICATORS.filter(row => row[2] === category)) {
          const node = byKey.get(key) || { node_key:key, label, acquisition_status:"awaiting_agent", review_status:"unsubmitted" };
          const [state, style] = nodeState(node); const button = document.createElement("button"); button.className = "graph-node"; button.dataset.node = key;
          button.innerHTML = `<span class="node-name"><span class="node-code">${key}</span>${label}</span><span class="node-state ${style}">${state}</span>`;
          button.onclick = () => { if (["P1", "P2", "P3", "P4"].includes(key)) this.onDetail?.(node, detailDescriptions[key]); else this.onNode?.(node); };
          stack.append(button);
        }
        card.append(stack);
      }
      grid.append(card);
    }
    scale.append(grid); this.container.replaceChildren(scale);
  }
  animatePersisted(events) {
    for (const event of events) {
      if (!event.node_id) continue;
      const node = this.nodes.find(item => item.node_id === event.node_id); if (!node) continue;
      const element = this.container.querySelector(`[data-node="${node.parent_key || node.node_key}"]`);
      if (element) { element.classList.remove("node-flow"); requestAnimationFrame(() => element.classList.add("node-flow")); }
    }
  }
  // 产品详情以鱼骨图呈现：产品为主干，核算要素和可点击来源节点为分支。
  renderFishbone(indicator, nodes, onNode) {
    const inputs = nodes.filter(node => node.parent_key === indicator.node_key);
    const row = document.createElement("div"); row.className = "fishbone-row";
    const productLabels = { P1:"农产品 · 玉米（已识别产品）", P2:"林产品 · 待建立经营产品目录", P3:"牧产品 · 待建立辖区产品目录", P4:"渔产品 · 待建立水体与产品目录" };
    const product = document.createElement("div"); product.className = "fish-product"; product.textContent = productLabels[indicator.node_key] || `${indicator.node_key} · ${indicator.label}`; row.append(product);
    const branches = document.createElement("div"); branches.className = "fish-branches";
    if (!inputs.length) { branches.innerHTML = '<div class="fish-empty">尚未建立该指标的核算要素。保留为待补充，不能视为零值。</div>'; }
    for (const input of inputs) {
      const [state, style] = nodeState(input); const node = document.createElement("button"); node.className = "fish-node";
      node.innerHTML = `<strong>${input.label}</strong><small>${input.value === null ? "等待可审核数据" : `${input.value} ${input.unit || ""}`}</small><span class="node-state ${style}">${state}</span>`;
      node.onclick = () => onNode(input); branches.append(node);
    }
    row.append(branches); return row;
  }
}
