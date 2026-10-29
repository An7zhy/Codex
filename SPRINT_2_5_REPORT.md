# Logistics Insight AI — Sprint 2.5 修复与部署准备报告

日期：2026-10-29（Asia/Shanghai）。

基线：`audit/remaining-issues-sprint-2`，`e2a106b25f845b9212720b0f09012ab5d161af75`；已从GitHub核对。
交付分支：`feature/sprint-2-5-readiness`。保留V1—V3、原Python算法、原Streamlit回退及Next设计。
没有开发V4/AI Agent、接入承运商或付费API，没有公开部署，没有读取/修改真实业务数据库。
测试数据、数据库、账号、容器与证书均为本地临时合成演练；不提供ZIP。

**结果：设置并发覆盖已修复；服务端只读合成实例与部署配置已实现；本地容器/TLS/资源/恢复行为已执行验证。**
最终pytest **395 passed / 0 failed / 0 skipped / 0 XFAIL**，原358项全部保留并通过，新增37项。
这不是公网放行，也不证明真实报价、容量、SLA、预测准确性或商业收益。

## 1. 已修复的代码缺陷

### PR-09：设置原子版本控制、草稿与审计

| 要求 | 实际实现 | 本轮证据 |
| --- | --- | --- |
| 持久版本与兼容旧库 | `web_settings.version`增量迁移，保留旧值并赋初始版本1；默认配置也入库，不是内存计数 | 旧两列设置表迁移后值与版本不变；重建Store及刷新后仍一致 |
| 读取/更新契约 | GET返回`priority/version`；PUT要求严格正整数`expected_version`，缺失/字符串/布尔/小数拒绝422 | 新版本/角色API用例；viewer/operator写403、匿名401；低权限也不能读配置差异历史 |
| 原子冲突保护 | 同一SQLite事务中`BEGIN IMMEDIATE`、`UPDATE ... WHERE version=?`、检查rowcount、写变更记录；不自动覆盖/重试 | 真正两线程/独立连接竞争，恰好一个成功、另一个409，仅一条成功变更 |
| 前端恢复与提示 | 草稿保存自身基准版本，导航/刷新不认领最新版本；409保留草稿并提示；Reload latest settings明确丢弃旧草稿 | 两管理员真实Chromium操作、切页仍拒绝旧版本、明确reload后成功 |
| 元数据与回滚 | `setting_changes`记录actor、UTC时间、旧/新版本、必要字段前后值；仅admin查询；10000条后507，不静默丢证据 | 精确差异`weights.urgency:30→81`；故意让审计插入失败，配置/版本一并回滚且503 |
| V2与决策上下文 | 版本进入比较指纹和保存案例快照；公式不变，改回相同值也使旧比较失效 | 原78.6667→88.1481、KPI不变、可用动作/已应用333与草稿444、幂等案例测试保留；ABA旧比较409 |

**实际复现原审计案例：** A/B同时基于版本1编辑，A把urgency设81成功，版本变2；
B把financial设82、携带旧版本1，返回409。数据库urgency保持81、financial保持20，
没有回到旧urgency30。B明确重新加载版本2后修改financial82，保存为版本3，两项修改都保留。
浏览器刷新及SQLite变更历史均核对；不是仅检查按钮显示。

独立恢复探针还按原审计的“先更改比较上下文、再双管理员覆盖”顺序执行，
也得到第二次409、`lost_update_reproduced=false`，恢复后版本/差异记录一致。

原358项的身份与数值断言保留。两个旧pytest用例和一个旧浏览器用例仅各补一行
GET当前版本作为合法更新的前置条件；原断言没有删除/放宽。新增用例单独验证缺失版本必须失败。
旧版没有版本号的设置草稿不会被自动赋予最新版本；升级后该类旧缓存需重新输入，正式配置不丢失。

## 2. 已完成的安全演示与部署配置

### 独立只读合成实例

- 完整业务应用默认仍为`LOGISTICS_INSTANCE_MODE=business`，保留原认证、角色、组织实例隔离、
  V1/V2上传分析和V3的Synthetic Demo/Uploaded Data两种模式。
- `demo`使用单独离线生成的密封数据库对。初始化只接受**新目录**，不接受业务文件、报价或账号，
  不覆盖已有目录。Docker演示数据库在只读镜像内，没有业务卷挂载。
- Demo服务端在正文处理前拒绝全部POST/PUT/PATCH/DELETE，包含登录、上传、方案比较、在线求解、
  设置和历史写入；GET也有明确允许列表。并非依赖前端隐藏按钮。
- 没有公开管理员/操作员密码，实际上**没有账号或会话记录**。访客是固定的合成viewer身份，
  不能获得业务会话；完整业务实例的无身份访问仍401。
- 验证实例用途、双库身份、SHA256、无WAL、总量上限、零账号/上传和内置V1规范源；
  不能用`synthetic=true`给客户表盖章。指定业务DB路径、篡改源表、混入账号或错误模式均失败关闭。
- SQLite按`mode=ro&immutable=1`打开，不进行在线迁移、建表或会话/限流写库；
  Demo采用每实例全局120 GET/min、同时2个操作、1024字节查询和空GET正文限制。
- 页面清楚标注只读及合成来源。可看/筛选KPI、异常、合成历史、预计算优化/MC和导出，
  不承诺在这个公开演示中执行完整应用的修改操作。完整应用相关功能保留且已回归。

### 容器与运维配置

| 配置 | 完成内容 | 边界 |
| --- | --- | --- |
| Python/Next/代理镜像 | digest固定基础镜像、独立web运行时、Next standalone、非root UID10001；支持正常联网或显式离线依赖构建 | Python传递依赖不是永久全锁；OS镜像CVE全量扫描未完成 |
| Demo Compose | 只发布`127.0.0.1:8443`；API8000/Next3000/内部health8080无主机绑定；数据网internal | 本地网络/绑定已检查，公网防火墙/目标Host规则未验收 |
| Pilot Compose | 保留完整受保护API；要求独立持久数据目录、专属hostname/来源、私有TLS目录；默认仍仅回环绑定 | 没有以真实域名启动该环境，也未申请公网证书 |
| CPU/RAM/PID | Demo API1CPU/1GiB/96PIDs；业务API2CPU/1536MiB/128PIDs；Next1CPU/768MiB/128PIDs；代理/监控另有限额 | 容器进程组边界，不等于每次解析的独立进程沙箱或生产SLA |
| 存储 | 根只读、cap_drop ALL、no-new-privileges；API/Next/代理tmpfs有限；日志轮转；Demo种子8MiB以内 | demo不积累订单/历史；TLS本地CA重建后会改变 |
| 业务物理存储 | 部署预检拒绝普通大文件系统，要求双库位于同一个最大1GiB的专用文件系统，保留8MiB余量 | Linux新建512MiB ext4示例脚本已提供，**未在执行宿主上运行特权挂载**；真实持久卷/加密/ACL仍由操作者验收 |
| HTTPS示例 | Demo用本地CA；Pilot为ACME配置示例；请求体/连接超时、安全响应头；内部端口不发布 | localhost证书链通过不等于公网可信证书通过 |
| 健康/通知 | 独立health/ready；监控每15秒检查API/网页/代理，3次失败输出ALERT，恢复输出RECOVERY | 本地日志通知，不是已经接通邮件/短信或值班系统；Docker不会自动重启仅unhealthy但未退出的进程 |
| 生命周期SOP | 停写双库原生备份/校验/新目录恢复/会话失效；保留、删除、备份副本到期及负责人/RPO/RTO步骤 | 手工机制真实可用，自动调度/异地副本/生产恢复时限没有虚构为完成 |

当前活跃的README、输入预览规则、中英文运行/架构/运维指南已更新两种V3模式，
也删除了活跃说明中“网站没有认证”的旧表述。历史审计/旧报告的原观察保留，并链接后续结果。

## 3. 已实际验证的运行行为

完整清单与逐项证据：[verification.json](docs/sprint2-5/verification.json)、
[pytest结果](docs/sprint2-5/pytest_results.json)。环境为Linux/Python3.12.14/Node24.19.0/Chromium。

| 实际执行 | 最终结果 / 证据 |
| --- | --- |
| `python -m pytest -q --junitxml=artifacts/sprint2-5/pytest.xml` | **395 passed，0 failed/skipped/XFAIL，172.94s**；原358项身份保留，新增37项；现有断言AST比对保持 |
| `npm run typecheck`及`npm run build` | 成功；原业务路由与standalone产物均保留；不是仅出静态页面 |
| `python -m scripts.verify_sprint_2_5` | 五组实际网页流程均通过，JS错误为空；原premium/hardening/uploaded、双管理员、只读demo；上传源/结果实际API进程重启保留 |
| 原V1/V2浏览器回归 | [premium](docs/sprint2-5/premium_browser.json)、[hardening](docs/sprint2-5/hardening_browser.json)：原数值、角色/来源、动作保存、501尾部异常、历史更新/删除 |
| 上传优化回归 | [uploaded](docs/sprint2-5/uploaded_browser.json)：100单完整上传确认求解导出、6000/9000/6000、无虚构概率、草稿恢复、28组响应式检查 |
| 并发UI与演示UI | [settings CAS](docs/sprint2-5/settings_cas_browser.json)、[本地demo](docs/sprint2-5/demo_browser.json)：真实409/重载、所有八个路由360/1440px不溢出 |
| 实际Docker构建 | API、Next standalone、非root代理、监控镜像构建成功；Docker构建DNS不可用，采用可信构建主机下载的固定要求/lockfile缓存离线安装，没有跳过依赖安装/Next构建 |
| `python -m scripts.verify_deployment` | [deployment.json](docs/sprint2-5/deployment.json)：真实本地TLS证书链/主机名校验，实际158 KPI和写入403；容器UID/只读/能力/端口/内网及内核cgroup值核对 |
| 存储与资源失败 | 根写入被拒；真实32MiB tmpfs写满ENOSPC、清理后ready200；独立32MiB容器分配128MiB触发实际OOM/137；未对API或用户DB做破坏性OOM压测 |
| 容器UI与恢复 | [HTTPS容器浏览器](docs/sprint2-5/container_demo_browser.json)16组路由/宽度通过；API真实容器重启身份/数据保留；停止API产生ALERT，重新启动后RECOVERY；临时容器/网络已清理 |
| 有界业务容器预检 | 真正64MiB tmpfs上的完整API启动、ready200/匿名workspace401；同容器的无界文件系统被拒绝。该tmpfs仅是演练，不宣称持久试点卷 |
| 停写CLI备份/恢复 | [recovery_probes.json](docs/sprint2-5/recovery_probes.json)：实际CLI，规划来源/结果/案例、设置版本和2条变更保留；旧会话401，新登录成功；损坏/留存/删除原回归也通过 |
| 配置校验 | Demo/Pilot Compose解析、Pilot Caddy实际validate、存储脚本`sh -n`均成功；Caddy验证在无网络容器中执行，无公网签发 |
| 验证工具保护 | [preflight_guard.json](docs/sprint2-5/preflight_guard.json)：预先存在同名项目时拒绝执行，不进入清理逻辑；以专门创建的临时容器验证其仍在运行，随后仅删除该测试容器 |
| 语法/依赖 | compileall、pip check通过；[Python扫描](docs/sprint2-5/pip_audit.json)、[npm生产扫描](docs/sprint2-5/npm_audit.json)均0已知公告；不是全面渗透或OS镜像扫描 |

**中间失败与处理：**

- 首次新增用例31通过/3失败：ASGI合法空GET可分多个空chunk，Demo错误地拒绝`more_body=true`。
  修复为在总5秒内读取完空chunk，任何实际正文仍拒绝；新增套件后通过。
- 首轮全套392项中391通过/1失败：与镜像构建同时运行，原500单测试的Fastest Delivery未返回可行解，
  原断言失败。单独原用例4.00s通过；停止重型构建后最终全套395通过。未修改求解算法、3秒参数或断言；
  不从这次通过推断负载下500单永远可行，也不补写首轮未记录的具体solver状态。
- 默认镜像内依赖下载因DNS失败；没有强行绕过安装，而是完整离线pip/npm安装和Next构建。
- Caddy原二进制的文件capability与ALL能力移除冲突，另有宿主配置权限导致非root读失败；
  镜像去掉不需要的文件capability，并以明确只读权限内置配置，保持非root/ALL drop，之后真实TLS通过。
- 第一次容器证据提取未找到CA文件；审计包装层改为等待并通过容器exec读取公有CA，
  再做真实链/主机名验证，没有用`verify=False`替代。新增恢复脚本的缩进错误也经compileall发现并修复、重跑成功。

这些不是最终通过项的替代；没有用skip/XFAIL、放宽断言、无限重试或假KPI掩盖它们。

## 4. 文件与运行入口

| 文件 | 用途 |
| --- | --- |
| `backend/store.py`、`schemas.py`、`main.py`、`access.py` | 设置版本/原子更新/差异历史/权限/比较指纹 |
| `web/.../settings.tsx`、`lib/utils.ts` | 持版本草稿、409提示、重新加载、类型化API错误 |
| `backend/demo_policy.py`、`boundary.py` | 密封源验证、只读服务端允许列表、拒绝写入与查询预算 |
| `scripts/prepare_demo.py`、Store只读连接及`src/history.py` | 新目录合成生成、封存、只读读取；业务默认行为不改 |
| `backend/deployment.py`、`scripts/serve_api.py` | 专用存储预检、受限服务进程入口 |
| `deploy/` | 三类Dockerfile、两个Compose、TLS示例、无密钥环境样例、Linux存储准备脚本 |
| `scripts/monitor_health.py` | 本地ALERT/RECOVERY通知 |
| `tests/test_readiness.py`、`browser_readiness.py`、验证脚本 | 新37项、原网页回归、真实容器/TLS/失败恢复 |
| [部署指南](docs/DEPLOYMENT_READINESS.md)、[中文指南](docs/WEB_RUN_ZH.md)、README | 当前模式、契约与可复现操作 |

本地完整应用保持原`python -m scripts.start_web`及独立Streamlit运行方式。
容器入口与离线构建步骤见部署指南；只读Demo没有需要公开的登录账号。
业务设置API现在必须带版本，外部脚本应先GET再PUT，不得自动给陈旧草稿套最新版本。

## 5. 仍需人工操作 / Not Verified

1. **公网验收未完成：** 目标DNS、公网可信证书、外部Host/入口/防火墙、Cookie/TLS跨站与外部端口扫描。
   所有本轮服务只在回环/私有容器网络运行，不能把localhost CA通过写成公网HTTPS通过。
2. **目标基础设施：** 每组织独立进程/域名/持久双库/目录ACL；实际持久有界文件系统、加密及私有TLS状态目录。
   Linux存储准备脚本未在宿主上执行；Windows/Docker Desktop/原生Python3.14未验收。
3. **资源与可用性：** 目标机器峰值输入、并发、持续负载、单次解析隔离与故障恢复耗时。
   内核限额已测但不保证合法大文件无服务降级；45秒worker、UNKNOWN/FEASIBLE语义继续保留。
4. **运营责任：** 指定备份/留存/告警负责人，异地副本、调度与真实RPO/RTO；将本地日志ALERT接到实际值班流程。
   设置变更元数据达到10000会明确507，需要停写备份后按既定政策归档；没有冒称已有自动归档平台。
5. **真实业务样本：** 获授权脱敏样本的字段、USD总价、时区/午夜SLA、快照首行重复规则、V2证据、报价/容量来源，
   由业务人员独立核对；跨批容量预留、航次/多段、真实可靠性校准和商业收益仍未实现/未验证。
   上传模式保留Not estimated，不把用户声明已核对当成程序独立验证。

## 6. 四个分别明确的结论

| 问题 | 结论 | 限定依据 |
| --- | --- | --- |
| 本地完整应用是否可用？ | **是，在已测Linux/Python3.12/Chromium范围内可用。** | 原358及新增37全部通过、原三个网页流程通过；认证、V1/V2/V3、上传优化、历史和设置冲突均真实执行 |
| 是否具备部署只读合成演示环境的条件？ | **已具备代码、配置和本地运行验证条件。** | 独立无账号合成只读源、服务端拒写、真实本地TLS与容器资源/失败恢复已测；目标环境仍须完成入口/证书/ACL/容量与责任人验收后再开放 |
| 是否已经完成公网验收？ | **没有。** | 未部署公网、未申请真实域名证书或验证外部防火墙/流量；本地CA仅用于本地验收 |
| 是否可以接收真实企业数据？ | **目前仍不应放行。** | 仍缺目标持久存储/权限/恢复/告警验收和获授权真实样本的业务口径确认。完成这些后再限定为单组织、受邀、固定模板、人工复核的试点，不要求先做V4 |
