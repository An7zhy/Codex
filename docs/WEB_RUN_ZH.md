# 新官网和业务平台：中文本地运行说明

新版本分支：`feature/sprint-2-real-input`。旧 Streamlit 仍可使用。

## 你会打开什么

- `http://127.0.0.1:3000`：新官网，大标题和原创动态科技图形。
- 点击 **Launch platform**：进入实际业务平台 `/app`。
- 左侧 Overview、Shipments、Exceptions、Decision Center、Optimization、Analytics、Settings
  各自切换到独立网页地址。
- `http://localhost:8501` 通常是旧 Streamlit，不是这次新官网。

## Windows：首次安装

1. 从 GitHub 下载 **feature/sprint-2-real-input** 分支，解压到独立文件夹，D 盘可以。
   找到包含 `start-web.bat`、`requirements-web.txt`、`backend` 和 `web` 的那一层。
2. 安装 [Node.js 24 LTS](https://nodejs.org/)，它包含 npm；建议使用 Python 3.12。
   安装后重新打开终端，让 PATH 生效。
3. 双击 **start-web.bat**。它会创建项目 Python 环境、安装依赖；首次运行会提示组织名、管理员账号和密码（至少12位，输入密码不显示字符）。随后构建前端并启动两个服务。
   第一次需要联网，终端出现下载和构建文字属于正常过程。失败时窗口会保留错误信息。
4. 等终端显示 `Website: http://127.0.0.1:3000`。浏览器通常自动打开；也可以手动输入地址。
5. 点击 Launch platform，用刚创建的账号登录。没有默认密码，也没有公开注册。使用期间保持终端打开。结束时在该终端按 **Ctrl+C**。

脚本通过 `py` 创建环境，后续直接使用 `.venv\Scripts\python.exe`，绕开可能有问题的
Windows `python` 应用执行别名。`app.py` 无需双击。

当前实际自动测试环境是 Linux / Python 3.12；**Windows 脚本执行及 Python 3.14
完整兼容性为 Not Tested**。已提供跨平台启动代码和手动步骤，不将其写成已通过的 Windows 验证。

## 手动安装（PowerShell）

在资源管理器地址栏输入 `powershell` 打开项目目录的终端，依次执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.2.2
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe -m scripts.manage_access setup
cd web
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m scripts.start_web --open
```

已有 `.venv` 可省略第一行。`npm.cmd` 可以避免 PowerShell 对 npm.ps1 的执行策略限制。
每行执行后等它完成，再输入下一行。

以后日常启动，无需重新安装：

```powershell
.\.venv\Scripts\python.exe -m scripts.start_web --open
```

更新过前端源码后，需要在 `web` 文件夹重新执行 `npm.cmd ci`、`npm.cmd run build`。
使用 `start-web.bat` 会自动完成这些步骤。

## 建议演示顺序

1. 官网点击 **Launch platform**，登录后默认 **Synthetic Demo Data**，分析日期 **2026-10-01**。
2. Overview 对照：158 单、47.8% 准时率、30 单运输中逾期、USD 539,830.75 有效运费。
3. Shipments 筛选状态、翻页、打开数据质量记录，下载结果 CSV。
4. Exceptions 查看分数、解释和缺失信息。Settings 将财务权重20改100并保存，
   `SYN-0027` 分数从78.6667变88.1481；Overview 的 V1 KPI 不应因此改变。
5. Decision Center 选择 `SYN-0027`，等待方案费用450、剩余48小时，点击 **Compare scenarios**。
   模拟延误应为24小时。之后只改费用草稿不会自动改变已应用结果。
6. 点击 **Save decision**；Handling history 中填写实际费用/延误、更新状态。
   刷新网页后记录应仍存在；重复保存相同决策不会无故多出一条。
7. Optimization 使用默认12单，点击 **Run optimization**；查看共享运力、三种策略与候选排除原因。
   Budget 改0%应返回 INFEASIBLE；开启允许未分配会显示12单未分配。
8. Analytics 查看已保存实验的模拟时间和逾期概率，并运行 V2 参考案例评估。
9. 恢复 Settings 的财务权重20、优化预算100%、容量100%、截止时间偏移0，便于下一次演示。

V3 的费用、运力与可靠性都是模拟参数，不能当真实报价或承运商准时率。
FEASIBLE 表示找到有效分配但未证明最优；UNKNOWN 不等于不可行。

## 常见情况

- **端口占用**：停止旧终端中的服务；也可以使用
  `.\.venv\Scripts\python.exe -m scripts.start_web --port 3100`，打开它显示的新地址。
  Python API 默认仍需要8000端口。
- **只看到旧 Streamlit**：检查浏览器是否仍打开8501；新官网通常是3000。
- **API 不可用**：确认启动终端没有退出，网页错误提示不会用虚构数据补位。
- **没有优化结果**：先到 Optimization 真正运行一次。Analytics 不会自动编造实验。
- **上传演示文件后指标变化**：检查顶部分析日期，演示应使用2026-10-01。
- **只有空表**：清除筛选；只有标题没有订单的文件是允许的，会显示空状态。
- **提示 Dataset not found**：浏览器记住了旧文件夹数据库中的数据编号。点击页面上的
  **Use Synthetic Demo Data** 恢复演示，或重新上传文件；不会自动删除旧数据。
- **更新保留历史**：停止服务，备份并保留原 `data/local/`；新网页和 Streamlit 共用原案例数据库。

不需要 API Key 或商业平台注册；本地管理员必须创建受邀账号。只读账号不能上传、求解或修改记录；操作员不能改权重或删除数据。

上传先点 **Preview import**，检查日期/重复订单/币种提示，确认规则后勾选再点 **Confirm import**。UTC日期零点不等于当地截止日结束；请先人工标准化。

远程试点与备份/恢复步骤见 [PILOT_OPERATIONS.md](PILOT_OPERATIONS.md)。本轮不代表已验证公网HTTPS或真实业务收益。


## Sprint 2：使用自己的运输规划输入

本轮先查看修复与检查报告，不需要制作或下载新的ZIP。运行方式保持不变。

1. 管理员或操作员登录后，进入 **Optimization**，将 **Optimization input mode** 选为 **Uploaded Data Mode**。
   **Synthetic Demo Mode** 仍是独立模拟沙盘；顶部V1/V2数据集不会被自动补成报价和运力。
2. 下载 **Excel template · 2 synthetic orders** 或 **100-order synthetic workbook**。
   也可以分别下载 shipments、transport_options、capacity、constraints 四个CSV。Excel标题的批注与
   **Field definitions and rules JSON** 解释字段；完整说明见 [PLANNING_INPUT_CONTRACT.md](PLANNING_INPUT_CONTRACT.md)。
3. 同时提供订单、每单候选报价、共享运力、单行约束。只接受 **USD / kg / m3 / h**，不猜汇率、
   磅/吨或体积换算。时间必须含明确时区，例如 `2026-10-03T00:00:00Z`，不能只写日期。
   所有订单共用 planning_start；同一service_id只写一份总运力，并必须有一致的预计运输小时。
4. 选择一个含四张指定表的Excel，或四个CSV，点 **Preview planning inputs**。查看错误表、单项约束排除、
   来源引用、数量、预算和单位。错误记录会留痕；修正源文件后重新预览，不能直接确认无效数据。
5. 检查无误后，勾选确认声明，点 **Confirm planning inputs**。服务器冻结输入并记录确认人和文件哈希。
   刷新或离开页面后可从 **Stored planning import** 找回，不需要把原文件缓存在浏览器里。
6. 点 **Solve uploaded plan**。查看三策略、共享容量和原始不可行诊断。成本/期限/容量互相影响，不能
   仅因每条候选单独通过就认定批量可行。FEASIBLE不等于已证明最优，UNKNOWN不等于不可行。
7. 下载 **Allocation CSV**、**Strategy CSV** 和 **Input & results JSON**。完整JSON保留输入和假设；
   上传结果不是旧模拟版CLI的Monte Carlo重放文件。无可行分配时CSV只有标题，不会虚构订单结果。
8. `estimate` 是估计；`user_verified` 仅表示上传者声明核对过相应引用，程序没有向承运商核实。
   **Not estimated** 表示没有可靠性估计，不是0%延误或100%准时。上传模式本轮不运行Monte Carlo。

先验证两单模板：最低成本和默认综合策略 **USD120**，最快策略 **USD180**。
100单模板对应 **USD6000 / USD9000 / USD6000**。这些都是可手算的合成样例，不能当作真实经营收益。

已增加：筛选刷新恢复；当前标签页中的决策草稿/已应用比较/备注、未保存权重、优化参数及历史结果编辑恢复。
未点击保存的草稿不会悄悄写入数据库。退出登录或会话过期会清除标签页草稿，避免账号混用；正式记录保留在SQLite。
保存恢复的旧比较时，若服务端配置已变化，会要求重新比较。浏览器禁用存储或标签页关闭后不保证恢复临时草稿。

管理员可删除规划导入及关联运行；离线保留清理和双库备份包含新导入表。公网HTTPS、目标电脑权限、
大负载和真实脱敏业务样本仍需单独验收；本轮不宣称已经具备承运商实时数据或预测能力。
