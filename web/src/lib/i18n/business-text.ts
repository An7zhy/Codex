/** Known deterministic narratives only; user-provided evidence remains verbatim. */
export function translateBusinessText(
  text: string,
  t: (value: string) => string,
  known: (value: string) => string,
): string {
  let result = text;
  result = result.replace(
    /Urgency: ([+-]?[\d.]+) hours to (.*?); window ([\d.]+)h\./g,
    (_, hours, source, window) =>
      `紧迫性：距 ${t(source)} ${hours} 小时；评估窗口 ${window} 小时。`,
  );
  result = result.replace(
    /Delay: supplied scenario estimate ([\d.]+)h; not inferred from overdue age\./g,
    (_, hours) =>
      `延误：用户提供的场景预估为 ${hours} 小时；不是根据已逾期时长推断。`,
  );
  result = result.replace(
    /Financial: declared estimate USD ([\d,.]+); basis: (.*?)\. This is not realized loss\./g,
    (_, amount, basis) =>
      `财务影响：声明预估 USD ${amount}；依据：${known(basis).replace(/[。.]+$/, "")}。这不是实际损失。`,
  );
  result = result.replace(
    /Value: declared USD ([\d,.]+) exposure context only; not a loss estimate\./g,
    (_, amount) =>
      `货物价值：声明 USD ${amount}，仅作风险敞口背景，不是损失估计。`,
  );
  result = result.replace(
    /Downstream: (\d+) declared dependent activities; basis: (.*?)\. Count is a proxy, not a failure probability\./g,
    (_, count, basis) =>
      `下游影响：声明有 ${count} 项依赖活动；依据：${known(basis).replace(/[。.]+$/, "")}。数量仅为代理指标，不是故障概率。`,
  );
  result = result.replace(
    /Missing inputs are not treated as low risk; no complete score assigned\./g,
    "缺失输入不视为低风险，因此不赋予完整评分。",
  );
  result = result.replace(
    /Weighted score is a triage heuristic, not predicted loss\./g,
    "加权评分仅用于异常分流，不是损失预测。",
  );
  // Finite lists returned by the rule engine; split separators, never raw JSON or identifiers.
  if (result === text && text.includes("; ")) {
    const parts = text.split("; ");
    const translated = parts.map((part) => t(part));
    if (translated.some((part, i) => part !== parts[i]))
      result = translated.join("；");
  }
  return result;
}
