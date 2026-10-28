# Logistics Insight AI — Sprint 2 修复、实现与验证报告

日期：2026-10-28（Asia/Shanghai）

开发分支：`feature/sprint-2-real-input`

基线：`fix/mvp-hardening-sprint-1`，提交`3489ddf17b3bd7c1a07a3a417a20dc16799fca2a`

## 结论

**已实现可运行的上传、严格校验、预览、确认留痕、原V3求解器求解及完整结果导出闭环。**
原288项测试均存在并通过，新增70项，共 **358 passed / 0 failed / 0 skipped / 0 XFAIL**。
原有认证、角色、单组织独立实例、上传/求解/存储预算继续生效，没有增加匿名业务入口。

本轮的“Real-Input”指用户输入的数据接入路径已经实现，**不代表已经用真实企业业务数据
验证运营效果**。本轮可独立计算的样例、100单输入和浏览器演练全部明确使用合成数据。
未提供新的ZIP或安排公开部署；本报告用于先评审功能正确性。

## 1. 按任务验收

| 任务 | 实际实现 | 验证证据 | 状态 |
| --- | --- | --- | --- |
| 保留Sprint1安全边界 | 新接口通过同一个ASGI认证/角色/来源边界；组织范围由服务端实例与双库身份确定 | 匿名新路由401；viewer直接预览/确认/求解/删除403；operator可导入求解、不可删除；B实例不能读A导入或使用A会话 | Implemented |
| 四张规划输入表 | shipments、transport_options、capacity、constraints，独立于V1/V2数据集 | 日期偏移换算、Order/Service/Candidate/Constraints映射、跨表引用与共享服务校验 | Implemented |
| 模板和字段说明 | 可下载含批注的四表Excel、四个CSV、字段/规则JSON；2单及100单合成样例，也可下载空标题模板 | Excel/CSV实际读入、100行模板、字段说明、布尔值及错误格式测试；浏览器下载模板 | Implemented |
| 严格校验 | USD/kg/m3/h固定契约；完整显式时区；价格、容量、期限、重复/未知引用及共享服务时效一致性 | EUR、空币种、lb/L/day、NaN/Infinity/负数/逗号、非法日期、重复ID、无效引用等被拦截 | Implemented |
| 预览、确认、留痕 | SQLite保存previewed/invalid/confirmed；源文件SHA256、上传者、确认者、时间、规则、规范化输入；确认后不可编辑 | 无效/未确认不能求解；错误摘要及前200条明示；修改确认指纹409；重复确认幂等；重启后保留 | Implemented |
| 复用原求解器 | 映射至现有dataclass和CP-SAT，调用原策略比较与独立可行性检查；没有另一套分配算法 | 两单独立枚举；100单成本及共享运力核对；不可行、软分配、极端约束和求解状态测试 | Implemented |
| 两种优化模式 | Synthetic Demo Mode保留原MC；Uploaded Data Mode只用确认输入、禁用风险权重和MC；最新运行/草稿分开 | 原网页全流程回归；模式切换、100单上传闭环、Analytics不显示虚构MC | Implemented |
| 来源与假设 | 每份运行绑定导入ID；JSON保留原表、来源文件哈希、确认和求解者、OR-Tools版本；CSV保留来源/引用/单位 | CSV100行成本与JSON一致；quote/time/capacity声明与引用可追踪；概率字段为空 | Implemented |
| 不可行诊断与导出 | 保留INFEASIBLE/UNKNOWN等语义、原候选排除与耦合约束诊断；失败CSV为空表并保留标题与来源标识 | 预算、重量、体积、件数、期限、路线、无候选均测试；不把失败或部分履约称为收益 | Implemented |
| 窄屏溢出 | 修复滚动表格中绝对定位的sr-only标题逃离容器；表格仍可横向滚动 | 28组页面/宽度检查包含Overview、Exceptions360/393与上传优化页面 | Implemented（本次设备范围） |
| 草稿/筛选恢复 | 筛选按账号/实例保存；决策选择、草稿/已应用比较/备注、权重、优化参数、历史实际值编辑保存在当前标签页 | 导航与刷新后恢复；333已应用/444草稿不混用；未保存权重和历史实际值不写DB；退出清缓存并拒绝API | Implemented（有明确缓存边界） |
| 生命周期 | 新表沿用共享配额、备份恢复和留存；管理员删除导入及关联运行；输入删除后在途求解不能复活数据 | 新表及关联运行恢复保留；过期导入级联清理；配额507；删除竞态409 | Implemented（离线运维范围） |

这里的Implemented均指所列实现和实际测试范围，不是“所有可能输入永不报错”或生产放行。

## 2. 数据契约与业务边界

详见英文 [PLANNING_INPUT_CONTRACT.md](docs/PLANNING_INPUT_CONTRACT.md)。

- 每批最多500单、100个共享服务、5000个候选和1行约束。一个四表XLSX或四个CSV；
  全请求20MiB、原接收时间/上传频率限制、XLSX展开/压缩比限制仍适用。
- 每单的报价是**已约定的总金额USD**，不是自动换算的每kg/每m3费率。缺金额不会零填；
  不猜附加费、汇率、货重或体积单位。规划表重复ID被拒绝，V1原先的快照规则不受此影响。
- 订单都从显式planning_start开始。同一service_id只声明一份共享重量/体积/件数，所有使用
  该服务的候选必须具有一致预计时效。不同单实际时效函数、航次时刻表或跨服务共享资源超出本契约。
- 完整ISO时刻必须含Z/offset；转换到UTC只是对显式时区的数学换算，不从起运地猜时区。
  无时区Excel日期、仅日期和模糊地区格式被拒绝。保留原求解器的保守整数取整。
- 硬约束先筛候选，再在共享预算/运力下分配；成本/时效偏好不能覆盖硬约束。
  综合策略沿用原成本1000USD、时间336h归一尺度；Uploaded Mode风险权重固定0。
- `estimate`与`user_verified`都有来源引用。后者只是**上传者声明已核对**，程序没有访问承运商
  或审计外部证据。未提供历史分布时，可靠性是Not estimated，不是0%延误或100%准时。
- Uploaded Mode完全不生成MC抽样；Synthetic Mode继续使用原假设与种子。所有结果显式标识来源。
  上传结果JSON使用独立schema；其原表可重新导入，不能冒充旧模拟CLI重放文件。

## 3. 独立计算与求解核对

### 两单实例

每单6kg/1m3；ECO共享容量仅1单，时效24h；FAST容量2单，时效12h。
两个截止时间分别为48h、24h，总预算200USD，综合权重100/0。

| 分配 | 独立计算总成本 | 是否可行 |
| --- | --- | --- |
| 单1 ECO、单2 FAST | 40+80=120 | 是 |
| 单1 FAST、单2 ECO | 100+50=150 | 是 |
| 两单FAST | 100+80=180 | 是，预计运输小时最少 |
| 两单ECO | 40+50=90 | 否，超过共享容量 |

实际：Lowest Cost=120，Fastest Delivery=180，Optimized Allocation=120，全部OPTIMAL。
这不是由综合评分公式生成的“准确标签”，而是对小实例的独立枚举。

### 100单模板端到端

50个ECO槽优先给每单节约60的奇数订单，另一组节约30。
独立最小成本是50×40+50×80=6000；全部FAST为9000。
实际通过上传、确认、独立worker求解及CSV/JSON导出验证：

| 策略 | 实际成本USD | 分配单数 | 状态 |
| --- | --- | --- | --- |
| Lowest Cost | 6000 | 100 | OPTIMAL |
| Fastest Delivery | 9000 | 100 | OPTIMAL |
| Optimized Allocation | 6000 | 100 | OPTIMAL |

真实执行的时间和运行状态见 [uploaded_flow.json](docs/sprint2/uploaded_flow.json)。
时间来自单机合成样例，包括明确标识的浏览器确认/求解往返与求解实验耗时；不是生产SLA或性能提升声明。
上述成本差异不代表真实经营节省或承运商报价。

## 4. 实际测试与命令

环境及完整结果：[verification.json](docs/sprint2/verification.json)，
[pytest逐项结果](docs/sprint2/pytest_results.json)。所有写入使用临时数据库；没有读取/改写用户业务库。

| 实际执行 | 结果 |
| --- | --- |
| `python -m pytest -q --junitxml=artifacts/sprint2/pytest.xml` | **358 passed，0 failed，0 skipped，0 XFAIL，184.10s**；原288项逐一比对名称、存在及通过状态，新增70项 |
| `npm run typecheck`、`npm run build`（web/） | 通过，保留全部原业务路由；最终版本复验见机器记录 |
| `python -m scripts.verify_sprint2` | 实际生产Next+FastAPI+Chromium，原premium流程及上传/草稿/权限/移动端/冷重启流程；证据见下 |
| `python -m compileall -q app.py src backend tests scripts` | 通过 |
| `python -m pip check` | 无依赖冲突；本轮没有增加依赖，不把此命令称为漏洞扫描 |
| 干净web-only venv导入Excel并调用原求解器 | 120/180/120通过、MC场景0，且没有安装Streamlit/Pillow/pytest；[证据](docs/sprint2/web_runtime.json) |

浏览器证据：

- [原网页功能回归](docs/sprint2/premium_regression.json)：V1/V2、原模拟优化/MC、上传导出、更新历史、错误和加载状态。
- [Sprint2真实操作](docs/sprint2/uploaded_flow.json)：100单闭环、来源、拒绝、不可行、缓存、28组窄屏/桌面检查、真实API进程重启。
- JS错误记录、成本/状态、测得时间及重启标志均保留；未用静态页面或伪造KPI替代后端。

独立核心求解器`engine.py`、`models.py`、`simulation.py`未修改。`experiments.py`仅新增可选
无模拟评估路径，默认模拟行为不变；新适配层负责映射、禁用不具备依据的可靠性输出和来源注释。
原288项pytest测试文件及断言未删除、改名或放宽。

## 5. 发现并修复的问题

| 问题 | 修复及验证 |
| --- | --- |
| 只有规划记录、尚未访问历史页的新实例执行retain时history.cases不存在 | 支持无历史表的空历史状态；留存计数包含规划导入和关联运行；测试通过 |
| 无解分配CSV可能没有标题，导致普通CSV读取失败 | 空分配保留列定义，0行；上传模式文件名/响应携带源导入ID；测试读取为空表通过 |
| 删除输入与在途求解保存之间的竞争 | 保存运行时在同一SQLite写事务中校验源仍已确认；已删除则409且不写结果 |
| 稀疏Excel很靠后的数据行可能落在预览读取范围之外 | 超出表行边界的工作表直接拒绝，提示清理额外行/格式；稀疏A1000回归测试通过 |
| 原Exceptions及特定筛选下Overview整页横向溢出 | 定位为隐藏表头的绝对定位容器问题；建立table-scroll定位上下文；保持表格内滚动；矩阵复验 |
| 页面切换/刷新丢失决策、权重、优化及历史编辑草稿，筛选重置 | 增加账号/实例范围的缓存；已应用值与草稿分开，保存仍做配置指纹/版本验证；退出清理 |
| 查看分配的分析时可能切到不同“最新运行” | Explore analytics链接绑定run_id，Analytics按明确运行读取，来源不随其他最新结果跳转 |

中间真实失败没有隐瞒：早期新增套件65通过/1失败暴露空历史retain问题；第一次完整浏览器
在移动端Overview360→376处失败，此前上传、求解、导出、权限和草稿操作已通过。
修复后重新测试；没有删除失败用例或将其标为XFAIL制造通过。

## 6. 文件变更与运行方式

| 文件/目录 | 用途 |
| --- | --- |
| `src/transport/input_contract.py`、`templates.py` | 表结构、字段说明、严格解析/校验、带批注模板与独立合成样例 |
| `src/transport/uploaded.py`、`experiments.py` | 原模型映射、无MC策略评估、来源/声明注释 |
| `backend/planning_routes.py`、`store.py` | 受保护导入、冻结确认、记录、求解、导出与删除 |
| `backend/runtime.py`、`optimizer_worker.py`、`boundary.py` | 复用原进程/角色/上传/配额边界并支持新入口 |
| `scripts/maintain_data.py` | 新表生命周期与空历史兼容 |
| `web/src/components/uploaded-optimization.tsx`、`optimization-results.tsx` | 双模式及共用真实结果展示 |
| `web/src/lib/session-draft.ts`、相关页面/样式 | 草稿范围、恢复、窄屏修复、结果来源关联 |
| `tests/test_planning_imports.py`、`browser_sprint2.py`、`scripts/verify_sprint2.py` | 新增70项自动用例与可重跑的真实浏览器验证 |
| README及中英文输入/操作说明 | 契约、限制与运行指引 |

原运行方式保持；本轮不要求现在查看网站。需要本地复验时按[中文指南](docs/WEB_RUN_ZH.md)，
使用现有venv和管理员创建流程启动。两种模式都在原Optimization页面，不会把V1文件自动猜成报价/容量。

## 7. 未解决和Not Verified范围

- **Not Verified：** 真实货代脱敏样本及业务有效性、真实报价/运力准确性、分布校准、商业收益。
  本轮合成样例证明的是接入、计算和资源约束一致性。
- **Not Verified：** Windows原生执行/具体Python3.14环境、公网HTTPS与入口/主机ACL、生产并发/浸泡、
  恶意档案全覆盖和生产RPO/RTO。Sprint1的部署验收条件仍然有效。
- **明确未实现：** 本契约的自动FX/单位转换/任意列名映射、实时API、自动订舱、多段/航班日历、跨运行运力预留；各批独立规划不能当作同时可执行；
  共享服务内每单不同运输时效、历史可靠性模型。上传模式只做有来源的确定性规划。
- **缓存边界：** 文件本体不缓存；可恢复服务端预览。草稿限当前账号/实例的当前标签页，单缓存上限512KiB；
  退出/会话失效清理，标签页关闭或存储被禁用不保证临时草稿恢复。正式记录仍在SQLite。
- **运维边界：** 仍需OS/容器CPU/RAM限制和受控部署验收；手动停写备份/留存机制不等于自动调度或异地容灾。

**建议：本轮代码闭环可进入下一轮受控数据核对；先用获授权样本人工验证字段、报价口径、时区和
容量池，再考虑真实业务试用。仍不将本地测试通过等同于可直接面向公网接收真实客户数据。**
