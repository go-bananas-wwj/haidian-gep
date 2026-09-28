const escapeHtml = value => String(value ?? "").replace(/[&<>"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]));

export function renderAssetCatalog(container, assets, type = "") {
  const selected = type ? assets.filter(asset => asset.asset_type === type) : assets;
  if (!selected.length) { container.innerHTML = '<p class="smart-empty">没有符合条件的数据资产。</p>'; return; }
  container.innerHTML = selected.map(asset => `<article class="asset-card" tabindex="0">
    <header><strong>${escapeHtml(asset.title)}</strong><span class="asset-quality ${escapeHtml(asset.quality_status)}">${escapeHtml(asset.quality_status)}</span></header>
    <p>${escapeHtml(asset.period_start)}—${escapeHtml(asset.period_end)} · ${escapeHtml(asset.asset_type)}</p>
    <dl><div><dt>许可</dt><dd>${escapeHtml(asset.license_or_access)}</dd></div><div><dt>SHA-256</dt><dd title="${escapeHtml(asset.sha256)}">${escapeHtml(String(asset.sha256 || "").slice(0, 16))}…</dd></div></dl>
  </article>`).join("");
}

export function renderHumanWork(container, items = []) {
  const labels = {needs_department_data:"等待部门数据",needs_business_decision:"需要业务判断"};
  container.innerHTML = items.length ? items.map(item => {
    const preview=(item.nodes || []).slice(0,5).map(escapeHtml).join("、");
    const packageName=item.type === "needs_department_data" ? "部门数据包" : "业务判断包";
    return `<article class="human-card"><strong>${labels[item.type] || escapeHtml(item.type)}</strong><span>${item.count} 个底层字段，已合并为 1 个${packageName}</span><p>${preview}${item.count > 5 ? " 等" : ""}</p></article>`;
  }).join("") : '<p class="smart-empty">当前没有人工事项。</p>';
}

export function renderCalculationChain(container, chain) {
  if (!chain?.plan) { container.innerHTML = '<p class="smart-empty">该结果没有自动计算链。</p>'; return; }
  const observations = (chain.observations || []).map(item => `<li>${escapeHtml(item.metric)}：${escapeHtml(item.value)} ${escapeHtml(item.unit)}</li>`).join("");
  const result = chain.run?.result;
  container.innerHTML = `<div class="calculation-chain"><p class="eyebrow">方法</p><strong>${escapeHtml(chain.plan.method_id)}</strong><p>${escapeHtml(chain.plan.explanation)}</p>
    <p class="eyebrow">输入</p><ul>${observations}</ul><p class="eyebrow">输出</p><strong>${result ? `${escapeHtml(result.value)} ${escapeHtml(result.unit)}` : "尚未执行"}</strong>
    <p class="muted">证据等级：${escapeHtml((chain.run?.quality?.evidence_classes || []).join("、") || "待记录")}</p></div>`;
}
