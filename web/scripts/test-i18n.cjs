/* No additional test runtime dependency: compile the same pure TS module used in React. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const root = path.resolve(__dirname, "../src/lib/i18n");
const modules = new Map();
function load(name) {
  const file = path.join(root, name.endsWith(".json") ? name : name + ".ts");
  if (file.endsWith(".json")) return JSON.parse(fs.readFileSync(file, "utf8"));
  if (modules.has(file)) return modules.get(file).exports;
  const module = { exports: {} };
  modules.set(file, module);
  const result = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
      target: ts.ScriptTarget.ES2020,
    },
  });
  new Function("require", "module", "exports", result.outputText)(
    load,
    module,
    module.exports,
  );
  return module.exports;
}
const { translate: t, translateExact } = load("translate");
const dictionary = load("zh.json");
let assertions = 0;
function eq(a, b) {
  assert.deepEqual(a, b);
  assertions++;
}
for (const [key, chinese] of Object.entries(dictionary)) {
  eq(t("zh", key), chinese);
  eq(t("en", key), key);
  eq(
    [...chinese.matchAll(/\{(\d+)\}/g)].map((x) => x[1]).sort(),
    [...key.matchAll(/\{(\d+)\}/g)].map((x) => x[1]).sort(),
  );
}
eq(
  t("zh", "User assumption with spaces\n第二行 "),
  "User assumption with spaces\n第二行 ",
);
eq(t("zh", "  自填来源 "), "  自填来源 ");
eq(translateExact("zh", "User remaining hours"), "User remaining hours");
eq(
  translateExact("zh", "User assumption with spaces\n第二行 "),
  "User assumption with spaces\n第二行 ",
);
eq(
  translateExact(
    "zh",
    "Simulation only; capacity, price and service commitments are unverified.",
  ),
  "仅为模拟；容量、价格及服务承诺未经核实。",
);
const raw = Object.freeze({
  shipment_id: "SYN-0027",
  status: "In Transit",
  service_id: "SHARED-ECO",
  risk: null,
  score: 78.6667,
});
eq(t("zh", raw), raw);
eq(t("zh", ["Wait and monitor"]), ["Wait and monitor"]);
for (const id of [
  "SYN-0027",
  "SHARED-ECO",
  "planning_start",
  "2026-10-01T00:00:00Z",
  "<img src=x onerror=alert(1)>",
])
  eq(t("zh", id), id);
eq(
  t(
    "zh",
    "Urgency: -24.0 hours to delivery_deadline; window 168h. Delay: supplied scenario estimate 48h; not inferred from overdue age. Weighted score is a triage heuristic, not predicted loss.",
  ),
  "紧迫性：距 delivery_deadline -24.0 小时；评估窗口 168 小时。 延误：用户提供的场景预估为 48 小时；不是根据已逾期时长推断。 加权评分仅用于异常分流，不是损失预测。",
);
eq(
  t(
    "zh",
    "financial: estimated_financial_impact and financial_impact_basis required; value: finite nonnegative shipment_value required",
  ),
  "财务影响：需要 estimated_financial_impact 及 financial_impact_basis；货物价值：需要有限且非负的 shipment_value",
);
eq(
  t("zh", "Wait and monitor: additional cost (USD)"),
  "等待并观察：追加成本（USD）",
);
eq(t("zh", "Wait and monitor: remaining hours"), "等待并观察：剩余运输小时数");
eq(
  t("zh", "用户名或密码不正确。 [HTTP 401]"),
  "用户名或密码不正确。 [HTTP 401]",
);
eq(
  t("zh", "Within deadline in scenario (24.0h spare)"),
  "场景中满足期限（余量 24.0 小时）",
);
eq(
  t("zh", "Misses deadline in scenario (24.0h late)"),
  "场景中超过期限（延误 24.0 小时）",
);
eq(
  t("zh", "2 order(s) have no hard-eligible candidate: ID-A, ID-B"),
  "2 条订单没有满足硬约束的候选方案：ID-A, ID-B",
);
eq(
  t("zh", "Invalid account or password. [HTTP 401]"),
  "用户名或密码不正确。 [HTTP 401]",
);
assert.match(
  t("zh", "Unrecognized safe detail [HTTP 422]"),
  /请求未成功.*Unrecognized safe detail.*HTTP 422/,
);
assertions++;
eq(t("zh", "FEASIBLE"), "可行，未证明最优（FEASIBLE）");
eq(t("zh", "Not estimated"), "尚未估计");
eq(t("zh", "Expected time"), "预计运输时间");
eq(t("zh", "{0} source rows excluded", [2]), "已排除 2 条源记录");
console.log(
  JSON.stringify({
    dictionary_entries: Object.keys(dictionary).length,
    assertions,
    passed: true,
  }),
);

// Guard future JSX additions: translated copy must have a dictionary entry, and option values
// may never implicitly derive from localized labels (which would alter API filter values).
let jsxFiles = 0,
  displayKeys = 0,
  options = 0;
const norm = (text) => text.replace(/\s+/g, " ").trim();
function template(n) {
  let text = n.head.text;
  n.templateSpans.forEach((part, i) => {
    text += `{${i}}${part.literal.text}`;
  });
  return norm(text);
}
function checkValue(n) {
  if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
    const key = norm(n.text);
    if (/[A-Za-z]/.test(key)) {
      assert.ok(
        Object.hasOwn(dictionary, key),
        `Uncatalogued display copy: ${key}`,
      );
      displayKeys++;
    }
  } else if (ts.isTemplateExpression(n)) {
    assert.ok(
      Object.hasOwn(dictionary, template(n)),
      `Uncatalogued display template: ${template(n)}`,
    );
    displayKeys++;
  } else if (ts.isConditionalExpression(n)) {
    checkValue(n.whenTrue);
    checkValue(n.whenFalse);
  }
}
function scan(file) {
  if (fs.statSync(file).isDirectory()) {
    for (const name of fs.readdirSync(file)) scan(path.join(file, name));
    return;
  }
  if (!file.endsWith(".tsx")) return;
  jsxFiles++;
  const source = ts.createSourceFile(
    file,
    fs.readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  function visit(n) {
    if (
      ts.isCallExpression(n) &&
      n.expression.getText(source) === "t" &&
      n.arguments[0]
    )
      checkValue(n.arguments[0]);
    if (ts.isJsxText(n) && /[A-Za-z]/.test(n.text))
      assert.fail(`Unlocalized JSX text in ${file}: ${norm(n.text)}`);
    if (ts.isJsxOpeningElement(n) && n.tagName.getText(source) === "option") {
      assert.ok(
        n.attributes.properties.some(
          (p) => p.name?.getText(source) === "value",
        ),
        `Option missing canonical value: ${file}`,
      );
      options++;
    }
    if (
      ts.isJsxExpression(n) &&
      n.expression &&
      !ts.isJsxAttribute(n.parent) &&
      ts.isBinaryExpression(n.expression)
    ) {
      const e = n.expression;
      if (
        [
          ts.SyntaxKind.BarBarToken,
          ts.SyntaxKind.QuestionQuestionToken,
        ].includes(e.operatorToken.kind) &&
        ts.isStringLiteral(e.right) &&
        /[A-Za-z]/.test(e.right.text)
      ) {
        assert.fail(`Unlocalized fallback in ${file}: ${e.right.text}`);
      }
    }
    ts.forEachChild(n, visit);
  }
  visit(source);
}
scan(path.resolve(__dirname, "../src/components"));
scan(path.resolve(__dirname, "../src/app"));
console.log(
  JSON.stringify({
    jsxFiles,
    checked_display_keys: displayKeys,
    canonical_options: options,
    passed: true,
  }),
);
