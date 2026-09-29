const FIELD_LABELS = {
  ecosystem_area: "生态系统面积",
  area: "核算面积",
  precipitation: "降水量",
  surface_runoff: "地表径流量",
  actual_et: "实际蒸散发量",
  npp: "净初级生产力",
  npp_or_nep: "净初级生产力或净生态系统生产力",
  respiration_or_conversion: "呼吸或转换参数",
  carbon_price: "碳价",
  carbon_sequestration_rate: "固碳量",
  quantity: "产量",
  harvest_quantity: "采收量",
  producer_price: "生产者价格",
  production_cost: "生产成本",
  intermediate_cost: "中间投入成本",
  visitor_count: "访问人次",
  travel_cost: "旅行费用",
  travel_time: "旅行时间",
  hourly_wage: "小时工资",
  attribution: "生态归因比例",
};

const STATUS_LABELS = {
  applicable: "适用",
  not_applicable: "不适用",
  verified_zero: "核验为零",
  pending: "待处理",
  pending_review: "待审核",
  unsubmitted: "未提交审核",
  approved: "审核通过",
  returned: "退回重查",
  auto_verified: "自动校验完成",
  awaiting_agent: "等待自动处理",
  agent_queued: "自动处理排队中",
  agent_running: "正在自动处理",
  candidate_ready: "已形成候选结果",
  research_complete: "公开检索已完成",
  manual_required: "需要人工确认",
  agent_failed: "自动处理失败",
  ok: "完成",
  complete: "完成",
};

export function fieldLabel(field) {
  const key = String(field || "");
  return FIELD_LABELS[key] || key || "未命名字段";
}

export function formatField(field) {
  const key = String(field || "");
  const label = fieldLabel(key);
  return key && label !== key ? `${label}（${key}）` : label;
}

export function statusLabel(status) {
  const key = String(status || "");
  return STATUS_LABELS[key] || key || "状态待确认";
}
