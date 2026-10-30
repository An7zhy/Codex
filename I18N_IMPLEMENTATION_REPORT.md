# Native Chinese / English Localization — Implementation and Verification

日期：2026-10-30（Asia/Shanghai）。基线：稳定 Sprint 2.5 `fc1115d`；开发分支：`feature/native-zh-en-localization`。

本次只升级 Next.js 展示层与必要的前端请求调度。没有更改 Python 算法、API 内部字段、SQLite 结构、认证/权限或服务端资源预算。没有公开部署，没有使用真实企业数据或本地用户的账号/密码。

## 1. 覆盖范围

| 界面 | 已本地化的内容 | 保留原文的内容 |
| --- | --- | --- |
| Landing `/` | 导航、Hero、功能/架构说明、实际数据预览、页脚、按钮和无障碍名称 | 产品/技术品牌、源代码链接 |
| 登录 | 组织登录、用户名/密码标签、加载、会话结束、无效登录提示、HTTP 状态 | 用户自行输入的账号和密码 |
| Overview `/app` | KPI 标签/统计口径、图表图例/提示、数据来源声明、快照与空状态 | 订单号、承运商/地点、源时间、数值 |
| Shipments | 上传/预览/确认规则、日期与重复订单警示、筛选、分页、数据质量、表头、导出按钮 | CSV/JSON 字段、原始值、用户文件名 |
| Exceptions | 队列、等级、评分解释、缺失证据、数据不足与仅供复核、分页/筛选 | 规则所引用的技术字段、用户自填依据原文 |
| Decision Center | 三种动作、成本/预计时间/期限影响、可用性、假设、草稿提示、保存反馈 | 提交/存储的英文动作枚举、用户备注 |
| 处理历史 | 查询/分页、状态、估计/实际值、编辑/保存、空状态 | 案例/订单编号、用户备注和审计字段 |
| Optimization | 合成/上传双模式、模板链接、输入校验、声明、确认、求解/约束诊断、结果/利用率/策略、导出 | 求解器原始枚举、服务编号、原始审计 JSON |
| Analytics | 真实计算/模拟的区别、策略比较、蒙特卡洛假设、参考案例与敏感性说明 | 原始 JSON 的键与导出数据 |
| Settings | 权重/尺度/阈值、版本冲突/重载、能力/限制、删除确认、KPI 定义 | 配置 JSON 的字段和值、版本语义 |
| 通用状态 | 加载、空状态、成功通知、错误、重试、404、移动菜单、跳转链接 | 未知新技术诊断的调试文本（附清晰中文概述与 HTTP 状态） |

受保护的完整业务实例与服务端密封的只读合成 Demo 使用同一翻译机制。
“合成数据”未翻译为真实业务数据；预计运输时间与实际送达时间明确区分。
`FEASIBLE` 展示为“可行，未证明最优”；`UNKNOWN` 不当作不可行；上传模式仍为“尚未估计可靠性”，不虚构逾期概率。

## 2. 技术实现

- `web/src/lib/i18n/provider.tsx`：一个根级 React Context，默认 `zh`；统一 `useI18n()` 与语言按钮。
  不用 locale 做组件 key，不刷新/替换工作区，不修改草稿、数据集或计算请求。
- `zh.json`：英文源文案为键、中文为值；英文模式返回源文案。静态字典与集中化的参数模板覆盖全部业务界面。
- `translate.ts`：仅转换传给展示层的字符串，数值/对象/React 元素不做递归转换。更具体的动态模板优先，保留技术 ID、数值及参数边界。
- `business-text.ts`：映射原规则引擎生成的紧迫性、延误、财务敞口、货物价值和下游解释。
  不解析或改写整份业务 JSON；非内置用户依据与备注保留原文。编辑框使用 exact-only 查询：只翻译目录中完整匹配的默认说明，不对用户文字套用动态模板；未知原文的空格和换行完整保留。
- 偏好使用一年有效的 `SameSite=Lax; Path=/` Cookie（HTTPS 下 `Secure`），供 Next 服务端渲染使用；localStorage 同步已打开标签页。
  该 Cookie 不是会话凭证，不能改变角色、组织身份或服务端权限。禁用浏览器持久存储时可在内存切换，但不保证刷新后保留。
- 根布局按偏好输出 `lang="zh-CN"` 或 `lang="en"`；客户端切换同步 lang/title。
  `translate="no"`、`notranslate` 与 Google no-translate 元数据提示浏览器不要自动改写 DOM。
  没有 DOM 文本替换、MutationObserver 翻译、insertBefore 补丁、错误吞掉或 hydration 警告抑制。
- 所有 `<option>` 明确给定原始 `value`，翻译仅影响标签；不翻译 URL、API 字段、请求体键、求解器枚举或 SQLite 内容。
- API 错误保留 HTTP 状态；已知错误映射中文，未知技术错误附清晰中文概述和必要原始诊断，不展示堆栈。

## 3. 发现并修复的问题

| 观察 | 处理 | 验证 |
| --- | --- | --- |
| 通用翻译模板先于更具体的“动作：剩余小时”匹配，导致动作部分没翻译 | 按固定文本的具体程度排序，并补精确断言 | 翻译单元测试与中文实际决策比较 |
| 文本节点巡检发现 KPI 定义名称与模板链接标签仍为英文 | 仅翻译相应展示标签，保持字段和链接不变 | 静态文案检查及实际中文页面文本复核 |
| 手机页头的面包屑和退出按钮较拥挤 | 小屏隐藏重复的工作区前缀，保留菜单/页名/语言/退出功能 | 双语 360px 截图及无溢出检查 |
| Demo 页面读取会话后，datasets/workspace/exceptions 可能同时发起，第三个读取触发原有并发上限 2 的 429 | 前端 GET 排队，包含响应体读取；取消/失败必定释放队列，写入不变；不自动重试、不吞掉错误 | 请求排队/取消/网络错误/429恢复单测，以及真实 Demo 浏览器巡检 |
| 通用翻译会规范化未知文字空白，不能直接用于可编辑备注 | 未知文字保留空白/换行，可编辑默认说明采用 exact-only 目录查询 | 备注换行/尾随空格单元断言及实际比较请求原文核对 |
| 密集页面巡检会触发原有每分钟请求预算 | 仅测试爬取按限额分批；不提升服务端预算 | 保留原安全测试与实际 Demo 拒写 403 |

新浏览器脚本本身也发现两处同步/定位问题：Next route-announcer 与登录错误同为 alert；分页页码在数据返回前已更新。
测试改为定位真实登录错误组件、等待并核对 API 返回的精确订单集合，然后再比较语言；没有删除或放宽任何既有断言。

## 4. 实际测试

最终执行结果与构建标识记录在 [verification.json](docs/i18n/verification.json)。所有7组浏览器结果对应同一最终构建及同一前端源码 SHA256。

| 命令 / 范围 | 结果 |
| --- | --- |
| `python -m pytest -q --junitxml=artifacts/i18n/pytest.xml` | **395 passed / 0 failed / 0 skipped / 0 XFAIL，171.11s**；原395项身份完全一致 |
| `npm --prefix web run test:i18n` | **通过**：1000条翻译词条、3026个翻译断言；605处静态展示键、24个显式原始option值；GET排队/取消/错误恢复/写入行为验证通过 |
| `npm --prefix web run typecheck` | **通过** |
| `npm --prefix web run build` | **通过**，保留所有独立业务路由；按Cookie动态服务端渲染 |
| `python -m scripts.verify_i18n` | **7组全部通过**：新增双语业务/只读Demo72组布局；原premium/hardening/uploaded/CAS/Demo五组均保留；所有pageerror记录为空，实际API重启与上传100单复验通过 |
| `python -m compileall -q backend src scripts tests`、`python -m pip check`、`git diff --check` | 已执行通过 |

浏览器使用本地 Next 生产构建、实际 Python API 和临时 SQLite；无页面数据 Mock、无真实用户账号。
原英文测试只在独立验证包装器中设置语言 Cookie 为 `en`，既有测试文件/数值断言完全不变。
新增中文验收核对：

1. 新浏览器默认中文；切换英文后刷新，实际服务端 HTML 仍为 `lang=en`。
2. 登录成功/失败双语提示；KPI API 计算值两种语言完全相同。
3. `In Transit` 原始筛选值、第二页订单集合、刷新后的筛选一致。
4. 待上传 File 对象、预览、确认、已上传数据集在切换后保持。
5. 中文方案实际追加成本 333 USD；动作枚举/备注与 SQLite 保存结果一致，评分来自已应用比较。
6. 未保存设置草稿 82 跨语言/导航保留，服务器配置仍为原 20，未隐式保存。
7. 中文合成优化返回实际 OR-Tools 分配；零预算返回实际 `INFEASIBLE`，不把诊断当单一约束证明。
8. 中文 EUR 导入拒绝并显示修正原因；两单上传案例手算成本 **120 / 180 / 120 USD** 与三种策略一致，可靠性保持未知，CSV ID 不变。
9. 只读 Demo 中英文均可读预计算结果，直接写入仍 403。
10. 每种实例的 9 个路由 × 2 种语言 × 360/1440px，共 36 组布局检查，捕获所有 pageerror。

原英文流程同时检查真实 100 单上传优化、6000/9000/6000 结果、API 进程重启后的持久化、权限/越权、决策一致性、设置并发409及只读 Demo。
这些是合成数据工程验收，不是企业业务数据或商业收益验证。

## 5. 有意不翻译与仍未验证的边界

- 原始 CSV/JSON、英文字段/求解器枚举、审计快照、代码/命令、ID、承运商/地点、时间戳、文件名、用户自填备注/来源保留原文。
  页面上的说明与错误已本地化，不把翻译后的标签重新提交给后端。
- 下载的运营分析报告仍为原有英文报告，按钮明确标注“英文报告”。原 Streamlit 回退界面不在本次 Next.js 双语迁移范围。
- 浏览器原生日期选择器、文件/确认对话框及原生表单校验气泡由操作系统/浏览器语言决定；应用自己的标签、说明与API错误支持双语。
- 第三方插件若无视禁止翻译提示强制修改 DOM，应用无法保证兼容；请使用自带开关并关闭自动翻译。
  本轮没有安装并操作 Google/Edge 自动翻译扩展，不声称验证了任意第三方 DOM 改写。
- Windows 原生启动/Python3.14、Safari/Firefox、真实手机硬件、本次新镜像的公网 TLS/负载与多用户峰值：**Not Verified**。
- 新增或未知后端技术诊断可能保留原始英文调试文本，需随 API 演进补充字典；不会编造业务原因。
- 本次未改变既有上线门槛，不代表已通过公网验收或可接受真实企业业务数据。

## 6. 证据与文件入口

- [最终环境/命令/构建/结果与中间问题记录](docs/i18n/verification.json)、[全部395项pytest结果](docs/i18n/pytest_results.json)。
- [双语业务实例](docs/i18n/i18n-business.json)、[双语只读Demo](docs/i18n/i18n-demo.json)。
- 原断言完整保留：[premium](docs/i18n/premium.json)、[hardening](docs/i18n/hardening.json)、[100单上传](docs/i18n/uploaded.json)、[设置并发](docs/i18n/settings-cas.json)、[原Demo](docs/i18n/legacy-demo.json)。
- [实际中文官网截图](docs/i18n/screenshots/landing-zh-1440.png)、[手机决策中心](docs/i18n/screenshots/app-decisions-zh-360.png)、[上传优化结果](docs/i18n/screenshots/app-optimization-zh-1440.png)。
- 新增：`web/src/lib/i18n/`、`web/scripts/test-i18n.cjs`、`test-api-queue.cjs`、`tests/browser_i18n.py`、`scripts/verify_i18n.py`。
- 修改：Next根布局、现有业务组件/共享组件、前端请求工具与样式、README、中文运行指南。没有新增Python业务模块或数据库迁移。

使用方式保持 `start-web.bat` / `python -m scripts.start_web --open`。需要下载/检出新分支并重新构建前端；旧的Sprint2.5 ZIP不会自动出现语言开关。页面顶部选择“中文 / EN”，并关闭浏览器自动翻译。
