# 克隆可用性预检 · 硬伤清单

> **本文件用途**：把「评委克隆后能不能跑起来」的审计发现，原样交给修文档的 agent 引用。
> **单一来源**：硬伤与文档缺口只在本文件定义，别处引用、不复述（遵守仓库的单一来源规则）。
>
> **审计方式**：只读审计 + 隔离环境实测。审计者未改任何被追踪文件、未碰主 `.venv`、
> 未占用 GPU（全程 `CUDA_VISIBLE_DEVICES=""`）、未下载 4.3 GB 权重。
> 隔离 venv 与「全新克隆」副本均建在系统临时目录下，不在仓库内。
>
> **实测环境**：Python 3.12.10（`py -3.12`）· Windows 11 · 官方 PyPI 源。

---

## 结论摘要

- **事实**：按 README 走，评委跑不起来——第①行命令在全新克隆上**必然崩溃**；
  而唯一能在全新克隆上跑通的入口（UI 演示界面）**README 完全未提及**。
- **判断**：修复量很小——一处 `parents=True` + 一个 `--photo` 参数 + 若干文档订正。
- **不构成问题的部分**（已核实，勿重复排查）：依赖清单完整可解、Skill 校验器实测通过、
  权重下载链接实测有效、无凭据泄露、`.gitignore` 对敏感路径全部生效。

---

# 第一部分 · 硬伤（7 条，按严重度排序）

## 硬伤 1 🔴 流水线 CLI 在全新克隆上必崩

**位置**：`skills/safety-hazard-detection/scripts/local_tier_pipeline.py:307-308`

**评委看到的原文**：

```
FileNotFoundError: [WinError 3] 系统找不到指定的路径：…\assets\real_photos\annotated
```

退出码 1。

**根因**：

- `:307` `photos = sorted((REPO / "assets" / "real_photos").glob("*.jpg"))` —— 读的是
  `assets/real_photos/`，该目录**被 `.gitignore` 排除**（理由：含可辨认人脸，当事人未同意公开），
  **克隆后不存在**。
- `:308` `(REPO / "assets" / "real_photos" / "annotated").mkdir(exist_ok=True)` ——
  **缺 `parents=True`**，父目录不存在即抛异常。
- **对照组就在下一行**：`:309` `(REPO / "models" / "runs").mkdir(parents=True, exist_ok=True)`
  —— 同一个函数里，紧接着一行就用了正确的写法。**这不是不懂惯用法，是漏了一处。**

**为什么评委绕不过去**：该脚本 `main()` 的 `argparse` 只有
`--runs` / `--tag` / `--legacy-severity` **三个参数，没有任何指定输入图片的入口**。

**同类脚本做对了，照搬即可**：`skills/evals/bench_layers.py`
- `:216-217` 提供 `--photo` 参数；
- `:227` 在图不存在时抛出**解释了隐私原因**的中文提示（「该图因含真实工人人脸、
  未获公开发布授权而不入库」），而不是让异常裸奔。

**实测方式（两轮）**：
1. 在「全新克隆」副本中用隔离 venv 真实执行该脚本 → 复现上述 traceback，`EXIT=1`。
2. 单独复现 `mkdir` 语义：在只有 `assets/samples/`、没有 `assets/real_photos/` 的目录树上
   执行 `:308` 那一行 → 同样 `FileNotFoundError`。

---

## 硬伤 2 🔴 唯一能在全新克隆跑通的入口，README 里不存在

**位置**：`ui/server.py`（评委入口）；`README.md`（缺失）

**事实**：`ui/server.py:63` `PHOTO_DIR = REPO / "assets" / "samples"` ——
界面读的是 `assets/samples/`（**已打码、随仓库提交**）。该文件的注释原话是
「评委克隆后点开就能跑」。**这是全套交付物里唯一一条不依赖任何不入库素材的演示路径。**

**但 README 里搜不到它**：对 `README.md` grep `ui/`、`server.py`、「界面」、「8770」
——**零命中**。`README.md:280` 的「项目结构」段落也**没有列出 `ui/`**。

**后果**：评委按 README 逐条走，只会撞上硬伤 1 的崩溃，永远发现不了这条能跑的路。

---

## 硬伤 3 🔴 截图泄露未打码人脸，使 README 的一句承诺变成假话

**位置**：`ui/screenshots/`（原 104 张，现 76 张）；`README.md:241`

**README 原话**：

> 我们刻意不公开该素材——照片仅在本地实验中用于验证链路，**公开仓库不含任何含人脸的素材**。

**实际情况**：`ui/screenshots/` 长期**未被 ignore**，会被常规 `git add -A` 收走。
清理掉重复文件后现存 **76 张，其中 48 张摄于打码文件生成之前**
（打码产物生成于 09-27 23:09；`pm-audit/` 摄于 22:02–22:16、`r2/` 摄于 20:01–20:21；
`hotfix/` 那一批为 09-28 03:15），当时界面显示的是**未打码原图**。

**决定性证据**：把 `hotfix/14-six-persons-done.png` 的照片区域按原始分辨率裁出、放大 3 倍后，
**蓝袍工人的侧脸完全未打码**（耳、颊、眼部清晰可辨）；而同一张图在 `assets/samples/` 里
对应位置的头部是一块大马赛克。人脸在截图中约 40×40 px（截图宽 1600 px）。

**为什么这条比「截图里有脸」更严重**：一旦入库，我们**不但在泄露，还会同时说一句假话**——
而那句假话正是我们自己写来承诺保护第三方的。

**当前处置**：`.gitignore:32` 已加 `ui/screenshots/`，经 `git check-ignore` 实测确认生效。
**请勿移除该行。**

**建议的 README 改写（已获批准）**：把 `README.md:241` 的绝对承诺，缩到我们真能兑现的范围——
> 仓库内图像仅含已打码样片与合成图；本地实验用未打码原图不入库。

---

## 硬伤 4 🟠 装环境缺一步，且解释器前后不一致

**位置**：`README.md:30-49`（安装段）、`README.md:67-71`（运行表）

1. **建 venv 这一步不存在**：安装段直接进入步骤 1 `./.venv/Scripts/pip install …`，
   但**全新克隆时 `.venv/Scripts/pip` 并不存在**。建环境的命令只出现在
   `README.md:49` 的脚注里，且标注为 `[未验证]`。**顺序错了：先建环境才能装。**
   同样问题见 `docs/DELIVERY.md:381`。
2. **解释器自相矛盾**：安装写进 `.venv`，但运行表 ③④⑤（`README.md:69-71`）与
   `README.md:135` 全部使用 `py -3.12`（**系统解释器**），只有 ② 用 `.venv`。
   照抄 ③④⑤ 必然 `ModuleNotFoundError`。

---

## 硬伤 5 🟠 `bench_layers.py --help` 在中文 Windows 上直接崩

**错误原文**：

```
UnicodeEncodeError: 'gbk' codec can't encode character '⚠' in position 783: illegal multibyte sequence
```

**位置**：`skills/evals/bench_layers.py` 的 `argparse`（`description=__doc__`，
文档串内含 `⚠` U+26A0）。崩在 `parser.print_help()` → `file.write(message)`。

**为什么评委一定会踩**：**中文 Windows 的默认控制台代码页就是 GBK（936）**。
而 `README.md:67` 第①行明写「参数以脚本内 `argparse` 为准」——
**等于引导评委去跑 `--help`**，正好踩中。

**已有的解法对这个入口无效**：`docs/DELIVERY.md:486` 已知此坑，给的解法是「加 `--out <file>`」。
但 `--help` 在解析 `--out` **之前**就已经死了，**该解法救不了 `--help`**。

---

## 硬伤 6 🟠 `docs/DELIVERY.md` 多处陈述已过期（会经 README 传导）

README 声明「本节命令**逐条取自 `docs/DELIVERY.md` §5**，未自行编写」，故 DELIVERY 的
过期内容会直接传导给评委。

| DELIVERY 位置 | 现状原文 | 实际情况 |
|---|---|---|
| `:425`、`:435` | 命令写 `…/models/bench_layers.py --layer $L` | **`models/bench_layers.py` 不存在**（已迁至 `skills/evals/bench_layers.py`，README ⑤ 是对的）。照抄报 `can't open file` |
| `:352` | 「📌 **下载脚本待补**：`fetch*.sh` 正在从 `models/` 移入仓库正式路径」 | **已过期**：脚本已在 `scripts/fetch_ms.sh` / `fetch_yolo.sh` / `fetch.sh` / `fetch_smol.sh` |
| `:354` | 「⚠️ 现有脚本**含本机绝对路径**（`cd /c/…`），**不可直接复用**」 | **已过期且方向相反**：脚本用的是 `cd "$(dirname "$0")/.."`，**是相对路径**，可复用 |
| `:505`（§5.6 第 4 条） | 处置列写「⏳ …**待脚本迁移**」 | **迁移已完成** |

---

## 硬伤 7 🟡 权重未下载时 UI 报错误导

**位置**：`ui/server.py` 的 `prewarm()`（冷启动加载 Tier 1 时）

**错误原文**：

```
huggingface_hub.errors.HFValidationError: Repo id must use alphanumeric chars, '-', '_' or '.'.
The name cannot start or end with '-' or '.' and the maximum length is 96: '<本地路径>/models/Qwen3-VL-2B-Instruct'
```

**原因**：`transformers` 在本地路径不存在时，把该路径当作 HuggingFace repo id 去校验。
按 README 顺序（先下权重）做不会遇到；但一旦跳过，**报错完全不提「模型文件缺失」**，
会把排查方向带偏。

---

# 第二部分 · 必须补进文档的 10 条

1. **快速开始补建环境**（置于步骤 1 之前）：`py -3.12 -m venv .venv`
2. **统一解释器**：把 `README.md:69-71` 与 `:135` 的 `py -3.12` 全改为
   `./.venv/Scripts/python.exe`，与安装位置一致（或全文统一用系统 Python，但必须一致）
3. **补 UI 启动方式**（评委最该看到的一条）：
   > `./.venv/Scripts/python.exe ui/server.py` → 浏览器打开 `http://127.0.0.1:8770`，
   > 内置三张**已打码**样片，点击即跑，**无需自备素材**
4. **第①行给出可跑的命令，并说清输入从哪来**：该脚本读取 `assets/real_photos/`
   （因肖像权不入库）。克隆后请用自备图片，或先把打码样片复制过去：
   `mkdir -p assets/real_photos && cp assets/samples/*.jpg assets/real_photos/`
   （**更好的做法**：给 pipeline 也加 `--photo`，与 `bench_layers.py` 对齐 —— 见硬伤 1）
5. **第⑤行补 `--photo`**：`--photo <自备工业场景图>`（仓库不含实拍图，必须显式指定）
6. **`README.md:280` 项目结构补 `ui/`**，并说明它是演示入口
7. **README 人脸承诺改写**（见硬伤 3，已获批准）；`.gitignore:32` 的
   `ui/screenshots/` **保持不动**
8. **`docs/DELIVERY.md` 的「待补 / 待迁移」改为既成事实**：
   `models/bench_layers.py` → `skills/evals/bench_layers.py`（`:425`、`:435`）；
   删去过期的「下载脚本待补」「含本机绝对路径」表述（`:352`、`:354`）；
   §5.6 第 4 条的「待脚本迁移」（`:505`）改为已完成
9. **补 `.env.example`**（仅三个变量名、无值）：`STEPFUN_API_KEY` /
   `STEPFUN_BASE_URL` / `STEPFUN_MODEL`
10. **补 LICENSE**：仓库根当前无 `LICENSE*`，公开仓库默认「保留所有权利」，
    他人无法复用

---

# 第三部分 · 本清单的证据边界（引用时请一并遵守）

**已独立实测通过、可放心引用**：

- `agentskills validate`：在干净 venv 中装 `skills-ref==0.1.1` → 提供 `agentskills.exe`；
  **4 个 skill 全部 `Valid skill`，退出码 0**。README 第②行「4/4 通过」属实。
  > ⚠️ **截至 2026-09-28 已过期**：新增 4 个 MES skill 后共 8 个，README 第②行已改为「8 个 skill」；
  > 8/8 实测见 `docs/DELIVERY.md` §7。**本条保留原文，仅标注。**
- `run_e2e.py --offline`：**`EXIT=0`**，写出 `offline-sample-report.md` / `offline-baseline.json`，
  **确实未覆盖** `a4-baseline.json`（README 的警告是准的）。
- `scripts/fetch_yolo.sh`：完整下载 **5,613,764 B**，
  md5 = `261474e91b15f5ef14a63c21ce6c0cbb`，**与脚本内写死的期望值逐位相同**。
- `pip install -r requirements.txt`：在隔离 venv 中**8 项全部按 pin 精确装上，无冲突**。
- README 引用的**全部交付物 / 真值来源文件**：逐条核过 26 个路径，**均存在**。
- `assets/samples/*.jpg` 三个文件 **md5 与 `real_photos/blurred/*_blurred.jpg` 逐位相同**、
  与原图不同 —— **打码供应链本身是对的，漏的只有截图**。

**未经独立复核、不得作为已验证引用**：

- **GPU 相关的一切**：审计全程 `CUDA_VISIBLE_DEVICES=""`，
  **冷启动 / 稳态延迟、显存数字一个都没有复现**。README 的性能表**未经独立复核**。
- **cu128 索引安装**：未实际执行（约 2.5 GB）。仅验证了「步骤 2 不会顶掉已装的 cu128 torch」
  这一逻辑（`ultralytics` 只要求 `torch>=1.8.0` / `torchvision>=0.9.0`，`transformers` 的
  `torch>=2.5` 仅在 extras 内）。
- **4.3 GB Qwen 权重完整下载**：按约定未下载。仅探到 `config.json` 返回 HTTP 200 且内容正确；
  **13 个文件中 `model.safetensors` 能否下完、断点续传是否可用，未验证**。
- **`run_comparison.py`**：需 API Key 与配额，未运行。
  **四臂消融的 480 次调用结果无法独立复核。**
- **UI 在权重齐备时能否端到端跑完一帧**：未接入权重再试。
- **打码覆盖率**：仅核了「样片 = blurred 文件」的 md5 一致性，并**肉眼确认 1 张图**的人脸被马赛克覆盖。
  **未跑人脸检测器逐脸核验**，无法断言三张图里每一张脸都被盖住。
- **截图含脸张数**：**做不到逐张判定，请不要引用任何具体张数**。
  审计中曾尝试用颜色特征筛（工厂照片的绿色地坪 + 蓝色工装）自动计数，
  **但校准环节即失败**：肉眼确认含未打码人脸的 `hotfix/14-six-persons-done.png` 只测到
  **0.67% 绿色**，而布局相近的 `pm-audit/20-stage-after-real-upload.png` 测到 **23.96%**，
  **相差 36 倍**——该指标实际测的是「照片被渲染成多大」，不是「有没有脸」。
  **故该工具的产出已被弃用，不作为任何结论依据。**
  可负责的表述仅为：**肉眼看过 2 张，其中 1 张确认含未打码人脸，1 张因渲染尺寸过小无法判定。**
  处置按最坏情况：**整个目录不入库。**

---

# 第四部分 · 环境相关（非仓库缺陷，但会卡住评委）

- **`pip install` 对部分国内镜像确定性失败**：本机配置的阿里云 PyPI 镜像上，
  `transformers==5.17.0` 不可得（该镜像最高仅 5.9.0），**换官方源 `--index-url https://pypi.org/simple/` 即恢复**。
  `docs/DELIVERY.md` §5.2 已记录此事，**保留即可**。
- **`py -3.12` 是 Windows 专用启动器**：非 Windows 环境需用 `python3.12`。
  `docs/DELIVERY.md` §5.6 第 6 条已声明，**保留即可**。
