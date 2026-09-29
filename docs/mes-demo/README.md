# MES 桥 · 最小可复现宿主页（示例数据）

**这是什么**：一份**独立可跑**的最小 MES 宿主页，按
[`docs/agents/mes-bridge-contract.md`](../agents/mes-bridge-contract.md) **v1.14 实现**——
不是从任何外部原型剪来的代码，全部 DOM 与 API 都是照契约重写的。

**为什么要有它**：MES 桥此前只能跑在一份**不在本仓库**的外部原型上，
⇒ 克隆本仓库的人**跑不起来**，演示也不能拍那份原型。
本页让「起服务 → 打开页面 → 落单出现在列表里」**只凭本仓库**即可复现。
它的第二个作用更硬：**证明那份契约是一份真接口规范，而不是对某一份实现的追认**——
同一份契约，被独立实现了一遍，仍然跑通。

> 🔒 本目录**全部数据为自造示例**，不含任何客户名或第三方数据。

---

## 同目录还有一份**完整原型**：`prototype.html`

**是什么**：一套**自建的 43 视图电子 MES 高保真原型**（单文件 SPA，1.3 MB），
进料检验 → 出货全流程。字段与流程对着**十份在用的产线样张**逐列对过。

**和上面那份最小宿主页什么关系**（两者不要混）：

| | `index.html`（本页） | `prototype.html` |
|---|---|---|
| 规模 | 最小 —— 只够跑通契约 | **完整 43 视图** |
| 用途 | 证明**契约本身**立得住（独立实现一遍仍跑通） | 桥接层就是为它写的，**演示拍的也是它** |
| 数据 | 自造示例 | 自造示例 |

两者**都按同一份契约**（[`../agents/mes-bridge-contract.md`](../agents/mes-bridge-contract.md)）工作 ——
所以桥接层换个宿主也能跑。

**打开方式**：和上面两条命令一样，把 URL 换成
`http://127.0.0.1:8000/prototype.html#view=qm-quality-exception`。

> 🔒 **已脱敏**：客户名、本机绝对路径、第三方缩写 —— **扫描全部为 0**。
> 正对照 `AgileMoM` 命中 **28** 处 ⇒ 零命中是「真的没有」，不是「没搜到」。
> 演示数据里的姓名**均为化名** —— 已核：在任何客户材料（10 份 `.xls` 样张 +
> 10 份 `.docx` + `forms_dump.txt`）中**零命中**。

> ⚠️ **上面那句「桥此前只能跑在一份不在本仓库的原型上」仍然成立** ——
> 指的原型是**带客户名的那一份**，它仍然不入库。本文件是**脱敏后的副本**。

## 两条命令

需要 Python 3（仅标准库）。在**仓库根目录**依次执行：

```bash
# 1) 起服务（必须在仓库根，页面按相对路径读 mes-data/inbox.json）
python -m http.server 8000

# 2) 打开（浏览器）
http://localhost:8000/docs/mes-demo/index.html
```

> ⚠️ **Windows 上若 `python` 报 `Python was not found`**（那是 Microsoft Store 的占位符，
> 不是真的 Python），把第 1 步换成 **`py -3 -m http.server 8000`**。
> 本项目 README 的「先 activate 再用 `python`」流程在这里不适用 —— 这一节不要求建 venv。
> （2026-09-28 在 Windows 11 + Git Bash 实测：`py -3` 可用。）

**应当看到**：表头计数 **`共 97 条`**（库内 96 条 + 本次落单 1 条），分页 `97` 条 / `13` 页，
列表**首行**出现 `QA-20260106-100`（高亮行），隔离列显示「未隔离」，状态徽标「待处理」。

> 合规 fixture **已随仓库分发**在 `docs/mes-demo/mes-data/inbox.json`，**无需任何准备步骤**——
> 打开页面就能看到落单。（它曾被设计成「运行期产物、由用户自己 cp」，但那会让默认状态
> 永远缺件：评委打开只看到空表。**一条永远红的默认门会被训练成「看见红也不当回事」**，
> 比没有门更糟，故改为直接分发。）
>
> 页面用 `fetch('mes-data/inbox.json')`（相对页面），故 `python -m http.server` 请**在仓库根**启动。
> 把它改坏了想恢复原样：`git checkout docs/mes-demo/mes-data/`。

### 想看点别的

| 想验证 | 怎么做 |
|---|---|
| §C.5 `iso: true` ⇒ 「已隔离」 | 把 fixture 里的 `"iso": false` 改成 `true`，刷新 |
| §F 失败可见性 ⇒ 红色横幅 | 把 `"schema_version": "1"` 改成 `"99"`，刷新 |
| §F 缺件静默 ⇒ 页面照常 | 临时移走 `inbox.json`，刷新：无横幅、计数停在 96。看完用 `git checkout docs/mes-demo/mes-data/inbox.json` 恢复 |
| §B.4 幂等 | 在左侧两个 tab 之间来回切 ≥2 次：计数**保持 97**，行不重复 |

---

## 示例数据是**真产出的**，不是手写的

`mes-data/` 下两个文件由**真 skill** 生成。重跑方式：

```bash
# 先清空 mes-data/（commit.py 是追加语义，不清会累积），再跑：
py -3.14 skills/mes-inspection-intake/scripts/commit.py \
  --finding docs/mes-demo/evals/finding-demo.json \
  --out docs/mes-demo/mes-data/inbox.json
```

**为什么必须这样**（§C.6）：手工写的文件**也能通过 schema 校验** ⇒ 「schema 合规」证明不了
「它由流水线产出」。本目录先前正是**手写的、且倒填了时间**（`produced_at ↔ mtime` 差 265 天）——
那正是 §C.6 点名的情形，评委照着契约一验就会验出来。现已改为真产出物。

**来源与可复现证据**（§C.6 认可的判别式）：

| 判别式 | 本项目实测 | 与环境有关？ |
|---|---|---|
| 同 fixture 重跑 | `inbox.json` **806B** / `xj-records.json` **458B**，**逐字节相同，仅 `produced_at` 不同** | **无关** ← 以这条为准 |
| `no` ↔ `rel` 序号 | 一致：`QA-20260106-100` ↔ `XJ20260106100` | 无关 |
| `produced_at ↔ mtime` | 本机刚产出时同秒（Δ<1s） | ⚠️ **有关**，见下 |

> 🔴 **`produced_at ↔ mtime` 不能当判据用**（把它留在这里是为了说清为什么）：
> **git 不保留 mtime** —— 任何 clone / checkout 都会把 mtime 刷成「检出时刻」，
> `cp` 复制同理。⇒ **在评委机器上 Δ 必然很大，而那不是缺陷，是刚被检出。**
> 一条在评委机器上必然报警的门，与一条永远红的门同类：都会被训练成「看见红也不当回事」。
>
> ⇒ 该值在本页自检里只作**信息性输出**（`INFO T15`，**不计 PASS/FAIL、不影响退出码**）。
> **来源结论只认「复现」**——那条与 git、与 mtime 都无关。
>
> （操作须知仍成立：**冻结/发布流程里不要用 `cp` 搬运产物**，要重跑 `commit.py`。
> 但那该写在文档里，不该靠一条会红的断言来传达。）

> ⚠️ `commit.py` 是**追加**语义（§C.4「追加，不去重」）。**重跑前必须清空 `mes-data/`**，
> 否则两条累积 → `data-total` = 98，破 §B.4 的 97。
> 本页生成的 `xj-records.json` 是 §C.2 要求的 `rel` 指涉对象（XJ 巡检记录），一并分发。

## 配套技能可直接查询本页（**不需要 `--proto`**）

`mes-record-query` / `mes-closed-loop` 原先只认一个**不在本仓库**的原型 ⇒ 装完跑不起来。
本页补齐了 §A.4 / §A.5 两个结构后，技能默认解析到本仓库内宿主页即可查到数据：

```bash
py -3.14 skills/mes-record-query/scripts/query.py --wo  MO-20260106-002   # → 生产中 / 1800 台 / SMT-2 线
py -3.14 skills/mes-record-query/scripts/query.py --dev FT-01            # → 飞针测试机 · FTA-300 / 在用
py -3.14 skills/mes-record-query/scripts/query.py --check MO-20260106-002 # → 已占用 —— 不可用
```

（`--proto` > `MES_PROTO` > **仓库内本页**；三者皆无才回头问用户。上面三条 `T14` 每轮都会真跑。）

> ⚠️ **已知消费方缺口（不在本页职责内，已上报）**：`st` 若被写成枚举外的值，
> `query.py` **不会报错**，会原样打印 `状态：bogus` 并 `EXIT=0` —— 对 agent 是**静默答错**。
> 本页的自检 `T12` 把这条兜住了（改坏 `st` ⇒ `T12`+`T14` 变红），但那是在宿主侧兜的。

## 契约覆盖

| 契约 | 本页实现 |
|---|---|
| §A.1 | `.mview[data-view="qm-quality-exception"]`；行属性 `data-no`/`data-rel`/`data-dept`/`data-status`/`data-date`；计数 `[data-count][data-total]`；分页 `.pagination span b` |
| §A.3 | 四态 → badge 映射（`found`→`badge-warning`/待处理、`handling`→`badge-info`/处理中、`recheck`→`badge-quarantine`/复验中、`closed`→`badge-success`/已关闭）；隔离列由 `setExcRow` 派生（`closed`→「已解除」，其余「已隔离」） |
| §B.1 | `addExcRow(sec, o)`：插入 + `data-created` +1 + 刷计数，**一次完成**；全局导出 `MESHOST.exc = { addExcRow }`（契约实质要求是「宿主把 `addExcRow` 暴露为一个全局」，**命名空间名由宿主自定**，本页取 `MESHOST`） |
| §B.2 | `excRowHtml(o)` 八字段 `no/rel/dept/desc/iso/finder/time/date`；状态写死 `found` |
| §B.1 计数公式 | `data-total = base + data-created`，`base` 惰性初始化 **96**（**不是行数**） |
| §B.4 | loader 幂等闸 `injectedNos`：同一 `no` 一次会话内最多注入一次 |
| §C.5 | `iso` 负映射在 loader：`true`→「已隔离」，**其余一律「未隔离」**（按 §C.5 默认 `false`） |
| §D | 两侧都堵：loader 侧 `stripQuotes()` 引号剔除 + 本页 `esc()` 连引号一并转义 |
| §A.4 | 工单：脚本数组 `var WORKORDERS`（5 条）+ 状态映射 `var WO_ST`（7 态，中文与 badge）；`line: null` 表示未派线（**不用空串冒充**）；另按契约**可选**项渲染成 `tr[data-wo]` + `data-colid` |
| §A.5 | 设备台账：**静态标注行** `<tr data-dcm-eq-row data-st="…">`（6 条，覆盖 在用/维修中/停用/已报废）；前 6 列＝设备编号·名称型号·所属工位·车间产线·接口类型·状态 |
| §E.1 | 「查询」触发元素标为 **`[data-q]`**（约定名），复现 600ms 回写窗口；loader 落在窗口内时**让开**再注入 |
| §F | 版本不认识 / 解析失败 → 红色横幅；`dept` 不在枚举 → 跳过并列入横幅；未知 `kind` → 跳过并计数；空数组 → 只记 console；**文件不存在 → 静默** |

**对照契约自测**（可选，需 playwright；本仓库 `.venv` 未装，故用系统 python）：

```bash
py -3.14 docs/mes-demo/verify_host_page.py     # Windows 下需 PYTHONIOENCODING=utf-8
```

**21 项断言**（另有 1 条 `INFO T15` 为信息性输出，**不计判定**），含五条**为证伪而设**的、
三条**跨技能集成**断言（T12/T13/T14），以及**四条字节卫生断言**（CR0/CR1/CR1b/CR2）：

- `CR0`：**本目录全部文件按字节扫，不得含 `\r`**（产物与页面文件一律 LF）。
  （产出侧根因已由 R2-S 修掉：`intake_core.py` 的 `write_text` 走文本模式 ⇒ 显式 `newline="\n"`；
  产物由 830B/475B 变为 **806B/458B**，差值 **24 / 17 恰好等于原 CRLF 的 CR 计数**。）
  🔴 **必须 `read_bytes`** —— 文本模式会把 `\r\n` 归一成 `\n`，**正好把要抓的东西抹掉**：
  工具自己消掉了自己要检查的东西（与「还原时刷 mtime、把要验的证据毁掉」同族）。
  该断言经**四向变异自证**：`CR1` 造出 CRLF **必须报**；`CR1b` 纯 LF **不得误报**；
  `CR2` 换回文本模式读后同一份 CR 样本**必须变哑** —— 否则 `CR1` 证明不了信号来自这条断言。
  真文件回归亦实测：把 `index.html` 整份改成 CRLF（448 个 CR）⇒ **只有 `CR0` 变红**；

- `T11`：**按分发的 `inbox.json` 原样加载**（不碰 fixture），且**期望值全部从产物现推**
  ——它是唯一覆盖「评委 clone 下来直接打开」那条路径的断言。
  其余各条都自带 fixture，所以分发的产物若坏了（`dept` 越界 / 版本不对），**整轮自检照样全绿**；

- `T7`：**不经 `addExcRow` 直接往 DOM 插一行 ⇒ `data-total` 必须不动**
  （证明计数确实走契约公式，不是数行数——「看起来对了」与「真走公式」的区别就在这里）；
- `T6`：先断言现行**确实是被注入的那一行**再做属性检查，避免断言落在种子行上**空转通过**；
- `T9`：**经全局入口 `MESHOST.exc.addExcRow` 调用一次，计数必须 96→97**
  —— 其余各条走的是 loader 内部直调，覆盖不到全局导出本身；
  少了它，「改名/重构把全局打坏」会**静默通过整轮自检**；
- `T10`：**在「查询」600ms 窗口内触发注入，该行必须仍在**
  —— 若 loader 硬插进窗口，回写会把它整体抹掉，于是 `data-total` 涨了 1、**行却没了**；
  这是「界面看着没事、其实丢了」的典型形态，靠计数根本发现不了；
- `T12`/`T13`：**调用真消费者的解析器**（`skills/mes-record-query/scripts/query_core.py`）来读本页，
  而不是自己重写一份正则 —— 否则「按我自己的理解解析成功」证明不了「消费者读得懂」；
- `T14`：**真的去跑** `query.py --wo/--dev/--check`，且**不带 `--proto`**，
  走的就是「装完直接问」那条路径。

> **本自检自身经过变异验证**（每条断言都要有抓错能力，抓不到即证明它空转）：
>
> | 变异 | 结果 |
> |---|---|
> | `window.MESHOST` 改名 | **只有 `T9` 变红**，其余照跑照过，无 traceback |
> | `[data-q]` 改回旧名 | **只有 `T10` 变红**（骨架行=0：点击不再触发查询） |
> | 拆掉 §E.1 让开窗口那行 | **只有 `T10` 变红**，且复现了真故障：`total=97` 但首行是种子行（注入行被抹掉） |
> | 把**分发的** `inbox.json` 的 `dept` 改成越界值 | **只有 `T11` 变红**，其余全绿——这正是 T11 补的那个洞 |
> | 工单 `st` 改成枚举外的 `bogus` | **`T12` + `T14` 变红**（`非法 st=['bogus']`、`缺状态=['running']`），干净 FAIL 无 traceback |

---

## 有意与既有实现不同之处（诚实清单）

| # | 差异 | 理由 |
|---|---|---|
| 1 | 本页 `esc()` **连引号一并转义** | §D 要求「两侧都要堵」。既有实现的 `esc` 只转义 `& < >` 是一个**已知缺口**，本页**不复刻**该缺口（loader 侧的 `stripQuotes` 仍按 §D 保留，两层都在） |
| 2 | `iso` 映射取 `r.iso === true ? 已隔离 : 未隔离` | §C.5 规定默认值为 `false`。若按「仅 `=== false` 才显示未隔离」，缺失字段会被**静默升级**成「已隔离」——那正是 §F 要防的静默失效 |
| 3 | 分页页大小 `PAGE_SIZE = 8` 为 **[团队自定]** | 契约未规定页大小。取 8 使 `96→12 页`、`97→13 页`，让「分页同刷」**可观测**（页大小取 10 时 96/97 都落在 10 页，该断言会空转） |
| 4 | `#mesBridgeBanner` 这个 id、以及错误态用 `rgb(179,38,30)` | 沿用本仓库既有测试台（`skills/evals/contract_bridge_loader.py`）已经观测的约定，便于同一套断言复用 |
| 5 | `refreshExcStats` = 本页状态统计；`refreshExcTotals` = 计数真源与分页 | 契约 §B.1 列出了这两个调用，但**未规定各自写什么**；此处按名字分了职责，两个都非空实现 |

### 本页**不**做的事

- **不落 DCM**（设备点检）：契约 §E.2 已裁决关闭，本页不实现。
- **不碰原型**：本页与任何外部原型无代码、无数据往来。
- **不写 `mes-data/` 之外的任何位置**。`mes-data/` 下两个文件是**随仓库分发的真产出物**（自造数据，
  由 `commit.py` 从 `evals/finding-demo.json` 生成）；自检脚本会临时清空/改写 `inbox.json`，
  并在结束时（**含异常路径**）逐字节还原——它们是跟踪文件，脚本崩掉也不能把它们留在删除状态。

---

## 相关

- 契约真源：[`docs/agents/mes-bridge-contract.md`](../agents/mes-bridge-contract.md)（v1.14）
- 桥的契约测试：[`skills/evals/contract_bridge_loader.py`](../../skills/evals/contract_bridge_loader.py)（针对被替换的原型；本页自带 `verify_host_page.py`）
