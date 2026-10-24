# Logistics Insight AI V2 — Stability & Quality Audit

**审计日期：2026-10-24（Asia/Shanghai）**

**范围：V1/V2 稳定性审查与修复；没有新增业务模块或开发 V3。**

结论：原有 103 项测试全部通过，但新增探针复现了原测试未覆盖的缺陷。
修复后最终 **132 / 132 项 pytest 通过，0 失败、0 错误、0 跳过，通过率 100%**。
真实浏览器回归、服务进程重启、100/500/5000 条数据测试也通过。
可以将本修复版本作为**受控 V3 迭代的基线**；这不等于已经通过真实物流运营或生产部署验收。

机器可读实测证据：[docs/audit_evidence.json](docs/audit_evidence.json)。
审计基线为 V2 提交 `514f2c9`；最终修复提交见本报告所在的 Git 历史。

## 1. 运行环境

| 项目 | 实际环境 |
| --- | --- |
| 操作系统 | Linux 6.18.55 x86_64，glibc 2.41 |
| Python | 3.12.14 |
| SQLite | 3.53.1，Python 标准库 sqlite3 |
| Streamlit / pandas | 1.50.0 / 2.3.3 |
| NumPy / Plotly | 2.5.4 / 6.3.1 |
| openpyxl / pytest | 3.1.5 / 8.4.2 |
| 浏览器自动化 | Playwright 1.62.0 + 环境内系统 Chromium |
| 依赖检查 | `pip check`：No broken requirements found |

本次没有升级运行依赖。Windows、macOS 和 Python 3.14 的完整审计均为 **Not Tested**。
下述耗时是本云环境的观察值，不能当作个人电脑的性能保证。

## 2. 测试范围与实际命令

审查了数据读取、质量清洗、KPI、异常规则、优先级、方案比较、SQLite、英文报告、
CSV 导出、Streamlit 展示和对照评估。检查了现有测试断言，并补充了真实失败的回归用例。

以下命令在项目根目录实际执行；`.venv/bin/python` 是本环境使用的解释器。

```bash
# 原有测试基线
.venv/bin/python -m pytest -q --junitxml=/tmp/logistics-audit-baseline.xml

# 新增回归用例的修复前复现
.venv/bin/python -m pytest -q tests/test_audit_regressions.py --junitxml=/tmp/logistics-audit-regressions-before.xml
# 额外发现的 CSV 结构歧义，修复前单独复现
.venv/bin/python -m pytest -q tests/test_audit_regressions.py::test_extra_csv_fields_cannot_silently_shift_shipment_columns --junitxml=/tmp/logistics-audit-ragged-before.xml

# 最终完整套件
.venv/bin/python -m pytest -q --junitxml=artifacts/audit/pytest-final.xml

# 修复前后性能测量：每个规模 3 次计算链路、1 次 AppTest
.venv/bin/python -m scripts.audit_benchmark --ui --output artifacts/audit/benchmark-before.json
.venv/bin/python -m scripts.audit_benchmark --ui --output artifacts/audit/benchmark-final.json

# 自动创建独立数据库/服务，执行真实浏览器测试和冷重启
BROWSER_EXECUTABLE_PATH=/usr/bin/chromium .venv/bin/python -m scripts.audit_browser

.venv/bin/python -m compileall -q app.py src tests scripts
.venv/bin/python -m pip check
```

部分命令的输出重定向到 `/tmp/logistics-audit-*.log`，底层退出状态被保留。
详细 JUnit、浏览器日志、下载文件和基准输出在忽略 Git 的 `artifacts/audit/` 下。
`audit_evidence.json` 汇总实际 JUnit 计数、失败名称、环境和测量值，不包含用户历史记录内容。

## 3. 自动测试结果及断言质量

| 阶段 | 总数 | 通过 | 失败 | 错误 / 跳过 | 通过率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原有 V1/V2 套件，修复前 | 103 | 103 | 0 | 0 / 0 | 100% |
| 第一批新增回归，修复前 | 14 | 6 | 8 | 0 / 0 | 42.86% |
| 额外 CSV 结构回归，修复前 | 1 | 0 | 1 | 0 / 0 | 0% |
| 最终完整套件 | **132** | **132** | **0** | **0 / 0** | **100%** |

最终完整套件实测 **15.822 秒**。没有遗留失败用例；没有禁用断言、标记预期失败或跳过失败项。
最终 pytest 没有测试警告；AppTest 的 bare-mode 日志提示不代表计算失败。

现有测试并非只验证“函数能运行”，例如：

- `tests/test_analysis.py` 对手算的 4 单样本断言送达 2、准时率 0.5、平均延误 24h、
  运输中逾期 1、成本 400，并验证完成延误与运输中逾期不重叠。
- `tests/test_priority.py` 对手算分项之和断言 Priority Score = 63.5，检查缺财务依据时
  不得以高货值补齐，不给完整分数，覆盖率为 80%。
- `tests/test_decisions_history.py` 以固定截止时刻断言三方案延误为 48/0/0h，
  修改加急假设后费用为 500、延误为 24h；并核对真实 SQLite 字段。
- 新增测试分别只启用 urgency/delay/financial/value/downstream 权重，断言固定手算
  结果 100/50/50/50/40；不是通过再次调用同一公式生成预期值。
- 新增规模测试的四种订单按固定比例构造。N 条的独立预期是：送达 N/2、完成延误 N/4、
  运输中逾期 N/4、准时率 50%、平均正延误 24h、成本 N×100、成本异常 0。

测试也有合理局限：V1/V2 等价比较属于回归检查，不能单独证明业务规则正确；
合成参考排序的一致性不是预测准确率。现有与新增测试结合了手算结果、边界断言、
存储检查和 UI 集成，但不宣称穷尽所有现实物流条件。

## 4. 修复前每个失败的原因

原有套件没有失败。下面是新增测试实际复现的 **9 个失败**，其中最后一项单独执行。

| 失败测试（简称） | 实际原因 | 修复后 |
| --- | --- | --- |
| `duplicate_named_headers...[csv]` | pandas 将重复成本列改为 `shipping_cost.1`，校验漏过，未抛出要求的输入错误 | 通过 |
| `duplicate_named_headers...[xlsx]` | Excel 重复表头同样被静默改名，无法确认应该使用哪一列 | 通过 |
| `damaged_excel_xml...` | 合法 ZIP 内的损坏 workbook XML 抛出未捕获的 `ParseError` | 通过 |
| `extreme_costs...` | 多条有限的 `1e308` 成本通过单值检查，聚合溢出为 `inf` | 通过 |
| `unchanged_repeated_save...` | 连续两次相同保存各生成 UUID，实际写入 2 条，而应复用同一提交 | 通过 |
| `invalid_saved_metadata...[assumptions_json]` | `not-json` 被持久化；后续详情解析可能阻断更新表单 | 通过 |
| `invalid_saved_metadata...[priority_snapshot_json]` | 优先级快照未检查 JSON 格式，同样可保存坏元数据 | 通过 |
| `mutated_priority_config...` | frozen dataclass 内的权重字典仍可变；被改成全 0 后发生 `ZeroDivisionError` | 通过 |
| `extra_csv_fields...` | 第一条记录多一列时 pandas 推断隐式索引，真实 ID `SYN-0001` 被丢成索引，起运地变成订单 ID | 通过 |

## 5. 问题分级与已实施修复

本次分级：High 表示可造成错误统计、重复持久化或核心上传流程中断；Medium 表示
配置/异常路径或测试隔离缺口；Low 表示规模增长带来的效率问题。未发现 Critical。

| 编号 | 级别 | 问题 | 修复与证据 |
| --- | --- | --- | --- |
| H01 | High | 有限大数仍能导致成本总额无穷大 | 增加 0～1e12 USD 技术范围；超限保留原值、记 invalid_cost、排除成本计算。不是市场价格基准 |
| H02 | High | 重复列与多余字段造成歧义/列错位 | CSV/Excel 在 pandas 改名之前检查原始表头；CSV 检查记录宽度。缺少字段的短记录仍可保留空值供质量审查 |
| H03 | High | 损坏 Excel XML 中断上传 | 解析异常转成可操作的 DataInputError，浏览器显示修复格式提示，无 Python 异常页 |
| H04 | High | 相同决策重复保存 | 持久化提交键和创建内容摘要；唯一索引保证重试只插入一次。刷新/重启后仍去重；不同动作/假设/备注允许新决策 |
| M01 | Medium | 坏元数据/错误类型可进入 SQLite | 写入时验证文本、有限数值和 JSON 对象；已有坏元数据只提示并保留，不阻断实际结果更新 |
| M02 | Medium | 权重字典可在验证后被修改 | 批量评分入口复制并重新验证配置，拒绝非法权重，防止除零/错误分数 |
| M03 | Medium | 原 AppTest 默认路径可能初始化真实历史库 | 全部 pytest 用例自动指向独立临时数据库；显式测试数据库也继续隔离 |
| L01 | Low | 下拉选项逐个全表查找，复杂度接近平方级 | 预构建 source_row→ID 字典，保持标签和业务行为不变 |

没有更改 V1 准时率分母、完成延误/运输中逾期定义、V2 五维评分公式或模拟方案业务含义。
唯一新增数值边界是防溢出的技术成本上限。原演示数据的核心 KPI 保持一致。

## 6. SQLite 与原数据保护

实际验证：

- 写入后逐字段读取；未知实际成本/延误保持 NULL，不填 0。
- 三个独立 Python 进程完成创建、更新、读取，结果一致。
- 真实 Streamlit 服务终止并重新启动，新浏览器仍能读到 Resolved、实际成本 150、实际延误 12h。
- 相同提交的连续点击、全新 AppTest 会话以及更新后的重试均不重复写入，也不覆盖已录入实际值。
- 四个并发相同请求只插入一条；`PRAGMA integrity_check` 返回 `ok`。
- 相同键携带不同内容被拒绝；明确的新提交键/变更后的决策可记录独立处理事件。
- ID、状态、异常类型和相似案例查询结果正确；逆向线路、不同模式、不同异常不被误匹配。
- 代表性旧 V2 表迁移后，记录数、状态、备注、实际值与版本均保留；重复初始化安全。
- 无效 JSON、非有限数值、负数及错误文本类型被拦截；旧坏元数据不被偷偷改写。

所有新增测试与浏览器服务使用临时库。原默认历史文件在新增回归前建立保护指纹，
全部检查完成后其字节指纹仍一致；没有把用户记录内容复制进报告。
审查发现原测试在“页面加载”时也可能初始化默认数据库，现已用自动测试夹具隔离。
实际用户数据库的部署迁移没有执行；只在临时代表性旧库上验证增量迁移，不删除历史重复记录。

## 7. Streamlit 与实际浏览器验证

AppTest 覆盖：主页面、筛选、空结果、输入变化、合法/非法权重、模拟方案修改、
保存与重复保存、状态/实际结果更新、相似案例、对照评估，以及存储不可用时 V1 仍可用。

真实 Chromium 验证：

- 原 V1 七项指标、四张 Plotly 图、CSV/Excel 上传、三类下载、筛选和移动宽度布局。
- V2 优先级与缺失信息队列、方案输入、保存、更新、刷新、评估 JSON 下载。
- 独立服务的健康检查、进程关闭、重新启动以及持久化记录读取。
- 真实上传 100/500/5000 条 CSV，等待当前数据的 V2 评分数量更新，避免把旧页面当成已完成。
- 5000 条数据下载后核对处理 CSV 为 5000 行、异常 CSV 为 2500 行。
- 空文件、缺列、重复列、多余 CSV 字段、损坏 Excel XML 均显示明确输入错误，不出现异常页。
- 100 条中混入错误日期、负成本、重复 ID：实际显示 99 个保留订单、49.0% 准时率、
  USD 9,800 成本、4 条质量问题；不是只检查页面是否打开。

成功运行中没有 Streamlit exception 元素或 JavaScript page error。

## 8. 100 / 500 / 5000 条数据与耗时

使用可复现的干净合成四场景数据，不冒充真实货代运营数据。计算链路包含 CSV 读取、
V1 分析、V2 优先级、KPI、报告、两个 CSV 导出和三方案计算；每个规模执行 3 次，取中位数。
AppTest 每个规模执行 1 次完整服务端脚本，并注入相应规模的数据，不等同于文件上传耗时。
浏览器列为真实 CSV 上传至当前优先级/决策组件可用，包含标签页导航。

| 订单数 | CSV 读取 | V1 分析 | V2 优先级 | 报告/导出等 | 计算链路中位数 | AppTest 单次 | 浏览器上传至决策可用 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 0.002 s | 0.040 s | 0.016 s | 0.033 s | **0.092 s** | 0.567 s | 2.883 s |
| 500 | 0.006 s | 0.055 s | 0.049 s | 0.066 s | **0.169 s** | 0.400 s | 1.126 s |
| 5000 | 0.035 s | 0.107 s | 0.443 s | 0.404 s | **0.990 s** | 1.595 s | 1.953 s |

所有规模计算与预设 KPI 一致，没有异常。表中各阶段分别取中位数，因此相加不一定等于总时长中位数。
首次 UI/浏览器运行有初始化成本；较小数据不一定更快。浏览器为本机暖会话顺序上传，
没有网络广域延迟或负载保证。修复前 5000 条 AppTest 观察为 3.083 s，
最终为 1.595 s；这是单机观察，不是统计显著的性能承诺。

## 9. 未解决问题、Not Tested 与人工步骤

本轮已复现的问题均关闭，**没有已知未解决的 Critical/High 复现项**。以下范围没有执行，
不能由本报告推断为已通过：

| 范围 | 状态 | 原因/下一步 |
| --- | --- | --- |
| Windows/macOS、Python 3.14 完整套件 | **Not Tested** | 当前执行环境为 Linux / Python 3.12 |
| Windows 原生文件选择器、D 盘/中文路径与浏览器翻译扩展 | **Not Tested** | 自动化使用 Chromium 文件输入，未控制用户桌面 |
| 原生 Microsoft Excel 打开下载文件 | **Not Tested** | 验证了文件字节、解析结果与公式文本转义，未启动桌面 Excel |
| 用户真实数据库的实际升级 | **Not Tested** | 按要求不写入用户库；仅验证代表性临时旧库 |
| 100,000 条、长时间浸泡、多用户压测 | **Not Tested** | 本次指定数据规模最高 5000，数据库并发限四个合成写请求 |
| 真实异常排序效用、预测/财务效果 | **Not Tested** | 只有合成工程验证，不具备真实承运商数据和业务评审 |

人工补测步骤：

1. **Windows / Python 3.14**：在包含 app.py 的目录打开 cmd，使用项目虚拟环境运行
   `.venv\Scripts\python.exe -m pytest -q`，记录实际版本与完整输出；
   再执行 `.venv\Scripts\python.exe -m streamlit run app.py`，不要双击 app.py。
2. **真实桌面文件选择**：通过 Browse files 选择 D 盘/中文目录中的 CSV、Excel；
   上传例子后将分析日设为 2026-10-01，对照 README 的 KPI，并检查错误文件提示。
3. **本地历史升级**：停止旧服务并备份 data/local；复制数据库到专门的测试目录，
   用 LOGISTICS_DB_PATH 指向副本后启动。核对原记录数、状态、备注和实际值，
   连续保存相同决策应不新增；改备注后应产生独立决策。不要先覆盖唯一原件。
4. **桌面导出**：在 Excel 打开处理结果，检查中文、USD、日期与 ID；需要保留前导零时
   按文本导入 ID。包含公式样式文本的测试字段应作为文本显示。

## 10. 稳定性与 V3 建议

**建议进入小范围、受控的 V3 开发。** 依据是：核心 KPI 与评分有明确数值断言，
原 V1/V2 回归保持通过，本轮高风险复现已修复，SQLite 保存/迁移/重试/冷重启被验证，
5000 条数据下计算和界面可用，审计工具可以复跑。

以本修复提交冻结稳定基线，并持续运行 pytest；若 V3 面向当前用户的 Windows/Python 3.14，
先完成上述平台补测。是否可投入真实货代生产运营，仍需真实脱敏数据、业务人员评审和部署验收，
不能用 100% 单元测试通过率或合成排序一致性代替。
