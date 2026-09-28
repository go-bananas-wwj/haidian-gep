export function nextActionFor({ active = 0, auto = 0, review = 0, gap = 0, expert = 0, failed = 0 }) {
  if (active > 0) return {
    kind: "wait", step: 1, disabled: true,
    title: "智能体正在替你准备数据",
    copy: `还有 ${active} 项在自动检索、提取和校验，无需手工操作。`,
    button: "等待自动研究完成",
  };
  const exceptions = expert + failed;
  if (exceptions > 0) return {
    kind: "exceptions", step: 2, disabled: false,
    title: "先处理真正需要判断的异常",
    copy: `${failed} 项执行失败、${expert} 项需要专家判断；系统会直接带你到第一项。`,
    button: `处理 ${exceptions} 个异常`,
  };
  const reviewable = auto + review;
  if (reviewable > 0) return {
    kind: "batch", step: 3, disabled: false,
    title: "确认智能体已经完成的工作",
    copy: `${auto} 项已自动校验，${review} 项建议复核。可整批确认，也可在弹窗中改为逐项审核。`,
    button: `整批确认 ${reviewable} 项`,
  };
  if (gap > 0) return {
    kind: "gaps", step: 2, disabled: false,
    title: "查看仍缺哪些正式数据",
    copy: `${gap} 项已完成检索但暂未找到合格数值，点击查看第一项的来源与执行记录。`,
    button: `查看 ${gap} 个数据缺口`,
  };
  return {
    kind: "scheme", step: 4, disabled: false,
    title: "数据准备已完成",
    copy: "下一步确认边界、版本和公式，再生成可复算快照。",
    button: "进入核算方案",
  };
}
