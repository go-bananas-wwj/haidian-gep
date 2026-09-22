export function renderMap(container, appendix) {
  container.replaceChildren(); const heading = document.createElement("div"); heading.innerHTML = "<h2>空间结果</h2><p>空间栅格仅在已核验的空间输入和覆盖质量报告存在时展示。</p>"; container.append(heading);
  const placeholder = document.createElement("div"); placeholder.className = "map-placeholder";
  const spatialReady = appendix?.rows?.some(row => row.input_nodes?.some(input => input.evidence?.spatial_support === "verified"));
  placeholder.innerHTML = spatialReady ? "<div>已存在经核验空间输入<br><small>地图图层由冻结结果提供</small></div>" : "<div>暂无经核验的空间化结果<br><small>不以 AlphaEarth 嵌入直接代替 NPP、ET、价格或成本数据</small></div>";
  container.append(placeholder);
}
