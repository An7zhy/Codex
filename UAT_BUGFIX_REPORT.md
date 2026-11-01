# UAT Bug Fix & Chinese User Testing

日期：2026-11-01（Asia/Shanghai）。基线：`feature/native-zh-en-localization` / `27fee90`。
独立修复分支：`fix/uat-chinese-filter-pagination`。

本轮使用临时单组织数据库、临时测试账号及明确标注的合成数据。
没有公开部署，没有读取/修改真实业务数据库；未改变数学优化模型、评分公式、认证角色、数据库结构或服务端资源预算。

## 1. 样本及复现范围

没有收到用户实际上传的原始120行文件，不能断言该文件的每列内容、63的来源或全部统计已核实。
本轮提供可独立计算的 [120条混合状态样例](data/uat/synthetic_uat_120.csv) 与
[120条活动异常样例](data/uat/synthetic_uat_120_active.csv)，规则见 [样例说明](data/uat/README.md)。
每表均为8个虚构承运商×15条，60空运/60海运、USD100/单，分析日期固定2026-10-01 UTC。

混合样例：37条在途异常、26条已完成延误、57条准时完成；83条有效完成，准时率57/83，
已完成平均延误20h，运费USD12000，成本异常0、V1质量问题0。未提供可选V2证据，37条活动异常均信息不足，无完整评分。

在**未修复构建**中，真实Chromium实际得到用户报告的第一页卡片 **7 / 0 / 7 / 13**，
队列完整总数 **63**，当前页20条。另实际复现：120条活动异常进入第二页后切换到只有37条活动订单的数据集，出现错误空状态。
证据：[baseline.json](docs/uat/baseline.json)，当时执行的源码：[baseline_probe.py](docs/uat/baseline_probe.py)。
该脚本是针对旧构建的缺陷刻画，不是要求修复版继续表现错误的回归测试。

## 2. 逐项判断与修复

| 项目 | 判断 | 依据、修复及范围 |
| --- | --- | --- |
| 单承运商没有其他条件时是否15条 | **Expected Behavior** | 真实CSV上传/预览/确认后，8个承运商逐个精确返回对应15个ID；API也逐一核对 |
| 方式/状态/关键词/组合筛选 | **Expected Behavior** | 方式/状态按原始值精确匹配，ID关键词不区分大小写、按字面匹配；条件为AND。承运商2+Air+In Transit为21/23/25/27/29五条；导出一致 |
| 有效组合返回0 | **Expected Behavior** | 承运商8无在途订单，组合In Transit合理为空；不是承运商筛选失效。增加完整生效条件、AND/ID搜索口径及“清除全部筛选”入口 |
| 已保存筛选不在当前选项中却看起来像“All” | **Confirmed Bug（展示）** | 原select没有对应option时可能显示空白/默认外观，而API仍应用旧值。保留并明确标注不可用筛选值；不静默丢弃业务条件 |
| 恢复过期订单页码导致假空列表 | **Confirmed Bug** | 原前端把API合法的越界空页解释为无匹配记录。现在发现offset超出总行数时回到第一页。实际注入offset1000后恢复到承运商8的15条，API原始offset语义未改 |
| 异常卡片与总数口径不清 | **Confirmed Bug（说明/汇总范围）** | 原卡片仅当前20条，标题为完整队列63。现卡片使用服务端在分页前计算的当前筛选汇总，另外明确显示数据集全部、筛选后及当前页数量 |
| 高优先级0、信息不足7 | **Expected Behavior（给定样例）** | 缺失/无效的启用评分证据不能生成完整评分；0个High不等于低风险。原文件的证据列需另核实 |
| 把四张卡片直接相加 | **Expected Behavior：不能相加** | High与信息不足都是活动异常子集。原第一页活动7包含信息不足7；7+仅复核13=20条。信息不足7不能再加一次；已排除源记录也可能进入队列 |
| 63是否等于质量问题条目数 | **未核实原文件；规则为Expected Behavior** | `exceptions.total`是异常订单记录数；`workspace.issue_count`是字段级问题数，可一单多项。新页面分别说明这两个单位，不强行让它们一致 |
| 活动分页跨数据集/范围保留过期页码 | **Confirmed Bug** | 原局部页码/搜索没有范围绑定；基线浏览器已复现假空页。新导航草稿绑定dataset/分析日期/共享筛选，变化回第一页并清空局部搜索；同范围刷新保留 |
| 局部搜索覆盖工作区关键词 | **Confirmed Bug** | 原hook直接覆盖q。现在保留全局q，新增有长度限制的局部`search`条件，与q及其他条件相交，不更改q原含义 |
| 单页按钮无页数说明 | **Confirmed Bug（交互反馈）** | 显示“第1页/共1页”；上下页禁用。120活动订单按50/50/20分页，页2精确51–100，能返回页1 |
| 原生中文React insertBefore异常 | **Not Reproduced** | 原生中文进入、选单、改参、比较、保存、查历史、切页、刷新返回均无pageerror；未安装或强制操作第三方自动翻译，不能声称所有扩展均兼容 |

## 3. 异常统计现在如何理解

| 数量 | 范围 | 混合样例（无筛选） | 筛选承运商1 |
| --- | --- | ---: | ---: |
| 数据集全部异常 | 当前选中数据集的异常源记录，未筛选 | 63 | 63 |
| 当前筛选异常 | AND筛选后、分页前的异常记录 | 63 | 15 |
| 当前页面异常 | 当前队列页实际记录 | 20 | 15 |
| 活动/待处理运输异常 | 分页前、符合原active_exception规则 | 37 | 7 |
| 高优先级 | 活动异常的High子集 | 0 | 0 |
| 信息不足 | 活动异常中无法完成评分的子集 | 37 | 7 |
| 仅供复核 | 完成/非在途/冲突记录，沿用原规则 | 26 | 8 |
| V1数据质量问题 | 当前筛选记录上的字段校验问题条目 | 0 | 0 |

换到第二页不会改变前述完整筛选汇总。没有为凑数字更改延误、在途逾期、V2证据要求或成本规则。
已完成延误与活动在途异常保持分开。

## 4. 实现边界

- `backend/main.py`：复用已算出的优先级分类做分页前汇总；`/api/exceptions`增加summary、数据集总数、局部ID搜索。
  原items/total/offset/limit及全局q保留；新search最多200字符，仍受原认证/组织实例边界保护。
- `workspace-provider.tsx`：恢复越界订单页；队列响应绑定请求范围，等待/取消旧请求时不把旧范围记录当新结果；范围重置及空页恢复。
- `decisions.tsx`：分页/局部搜索与范围一起保存；单页反馈、完整筛选可见；未改变方案比较/保存逻辑。
- `operations.tsx`：显示全部AND条件和不可用旧值；异常卡片改用完整筛选汇总，清楚列出包含关系和单位。
- 所有新文案进入原中英字典，筛选option仍使用原始value；没有DOM翻译、insertBefore补丁或错误抑制。
- 旧版不带范围的decision-page/decision-search不自动迁移；方案参数、已应用比较、选择动作、备注使用的原草稿键保留。
  用户切换范围时局部搜索明确清空，而同范围导航/刷新保留状态。
- 共享筛选跨页面仍会保持，这是可见的筛选规则；切换数据集清空共享筛选与订单页码，根数据来源、KPI随数据集切换。

## 5. 实际执行的测试

运行环境：Linux、Python3.12、Node24、Next生产构建、真实Chromium及临时SQLite。
全部原395项Python用例、原浏览器断言及中英文机制保留；新增17项API回归和中文UAT浏览器脚本。

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q tests/test_uat_filters.py` | 首轮17 passed，9.10s；随后补入同用例的独立KPI断言，由全套复验 |
| `.venv/bin/python -m pytest -q --junitxml=artifacts/uat/pytest.xml` | **412 passed / 0 failed / 0 skipped / 0 XFAIL，141.28s**；原395项身份全部保留，新增17项 |
| `npm --prefix web run test:i18n` | **通过**，包括翻译目录/静态展示/原始option值与请求调度回归 |
| `npm --prefix web run typecheck` | **通过** |
| `npm --prefix web run build` | **通过**，保留所有原路由 |
| `.venv/bin/python -m scripts.verify_i18n --flows uat --evidence-root docs/uat --artifact-root artifacts/uat` | 已通过；8×15、AND/导出、旧offset、完整统计、中文决策/历史、120活动分页、16组中英文360/1440布局均实际执行 |
| `.venv/bin/python -m scripts.verify_i18n --flows uat,i18n-business,i18n-demo,premium,hardening,uploaded,settings-cas,legacy-demo --evidence-root docs/uat/regressions --artifact-root artifacts/uat/regressions` | **8组全部通过，同一最终构建/源码指纹**；新增UAT16组布局，原双语72组布局及原英文5组均通过，pageerror全部为空 |

测试遵守原有请求预算，必要时分批；没有提升服务端配额或Mock业务响应。
初次UAT新脚本在搜索处失败：合并分页/搜索状态后旧处理器又执行一次setPage(0)，把新搜索覆盖。
已删除冗余写入，由setSearch原子重置页码，保留精确订单断言后重跑通过。
没有删除、跳过、放宽原有测试断言。最终结果及中间失败记录以证据为准。

## 6. 使用及仍需核实

- 中文操作：上传样例并确认，查看“当前生效筛选”，单选承运商前清除其他条件。关键词只搜订单编号。
- Exceptions先读统计口径；信息不足时补充有效V2证据，而不是把货值当实际损失或随意提高分数。
- Decision Center：同范围刷新保留分页与草稿；改变数据集/分析日期/共享筛选会清空局部搜索、回第一页。
- 仍需用户原始文件才能核实其8个承运商是否有额外空格、错误行、重复ID或合法V2证据；本轮合成复现不能替代原文件审计。
- Windows/Python3.14、真实设备/其他浏览器、强制自动翻译插件、企业真实数据、生产并发与公网验收：**Not Verified**。
- 继续使用原启动方式；未自行部署公网。报告不构成接收真实企业数据的上线放行。


## 7. 最终证据与结论

- [环境、构建指纹、命令和汇总](docs/uat/verification.json)、[全部412项测试结果](docs/uat/pytest_results.json)。
- [新中文UAT流程](docs/uat/uat.json)：包含无效旧筛选值、8×15、真实导入/比较/保存/历史和120活动分页。
- [双语业务版](docs/uat/regressions/i18n-business.json)、[双语只读Demo](docs/uat/regressions/i18n-demo.json)。
- [原premium](docs/uat/regressions/premium.json)、[权限/保存回归](docs/uat/regressions/hardening.json)、[100单优化与API重启](docs/uat/regressions/uploaded.json)、[配置并发](docs/uat/regressions/settings-cas.json)、[原Demo](docs/uat/regressions/legacy-demo.json)。
- [实际中文异常页](docs/uat/screenshots/exceptions-zh-1440.png)、[360px手机布局](docs/uat/screenshots/exceptions-zh-360.png)。

**结论：在已测Linux/Chromium、本地单组织受保护实例范围内，修复后的中文上传、筛选、异常统计、方案比较、保存、历史查询和分页闭环可用。**
8组浏览器流程均对应同一最终Next构建及前端源码哈希；原有测试文件逐一字节比对未变。
对原始用户文件及第三方强制自动翻译保持未验证结论，不把“未复现”写成“永不出错”，也不宣称达到公网或真实企业数据接入标准。
