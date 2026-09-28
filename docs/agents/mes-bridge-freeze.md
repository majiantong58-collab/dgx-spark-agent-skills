# MES 桥契约测试台 · 封版冻结记录

> **冻结于 2026-09-28，提交 `306bf90`。契约 v1.14。**
>
> **这份记录为什么在仓库里**：冻结的价值在于**能被别人核**。
> 只存在于对话或某台机器上的哈希，对评委等于没冻。这里给出可复现的字节、实跑数字与复现步骤。

---

## 1. 冻结哈希与依赖集（canonical）

**canonical = 把 CRLF 归一成 LF 后计算 sha256。** 理由见 §3。

| 类别 | 文件 | canonical sha256 | 字节 | CR |
|---|---|---|---|---|
| 测试台 | `skills/evals/contract_bridge.py` | `16022f2773d7972b6c73d67023d75ce7a1de49474c69301022cb9d22470c9a7f` | 60664 | 0 |
| 测试台 | `skills/evals/contract_bridge_loader.py` | `4a8a7098efaf31a62c7c42b1387a77969793d462915ff5a6a90ab1ac707acb7a` | 34725 | 0 |
| 测试台 | `skills/evals/contract_bridge_delivery.py` | `7f5a376afe0fa1809e6c10bb0e7f61ce3b3ec66803f0ffd71cb9d092e8de5f4f` | 22957 | 0 |
| 依赖·契约 | `docs/agents/mes-bridge-contract.md` | `0ecc7b8d81765468f0dfc1bf8ba3b987b2697788005fbe7997b6e405d16b4043` | 31343 | 0 |
| 依赖·宿主 | `docs/mes-demo/index.html` | `66cb46f674a37e741344d4f02ca98be8afe60b39013c6494fbda3fe8a13fc0db` | 24743 | 0 |
| 依赖·产物 | `docs/mes-demo/mes-data/inbox.json` | `d6ab9fbdb39c6920206542c35115989142cf581a997b23189fb82626214269bd` | 806 | 0 |
| 依赖·产物 | `docs/mes-demo/mes-data/xj-records.json` | `b42a41b8d3ef20238456b8eb42cfbb551eb18160d1967a208592932ac1098b66` | 458 | 0 |
| 依赖·实现 | `skills/mes-inspection-intake/scripts/commit.py` | `eccc79ac56ba71d43dd6c5dd806d9c3158c2209187044cc3c30eba9cb706ec6a` | 2712 | 0 |
| 依赖·实现 | `skills/mes-inspection-intake/scripts/intake_core.py` | `07740f5b13e46abda46fd04613036d341e6ba96ee8c1f5105751dd8e7f4fd858` | 17986 | 0 |
| 依赖·夹具 | `skills/mes-inspection-intake/evals/fixtures/finding-demo.json` | `6e5bbd8dac2e3168d6a08b3700ea2636b8ae1762114e20bd74601a7c182440e5` | 804 | 0 |

> 表中 `CR` 一列全部为 0（工作区与仓库同为 LF）。这不是靠约定写死的，而是 §4 的复现脚本**实际会核**的东西。

---

## 2. 四个门 + 各自变异自检的实跑数字

| 门 | 命令 | 结果 |
|---|---|---|
| skill 侧 + 集成半场 | `py -3 skills/evals/contract_bridge.py --loader` | **30 PASS / 0 FAIL / 0 SKIP**（exit 0） |
| 变异自检（skill 侧） | `py -3 skills/evals/contract_bridge.py --selftest` | **22/22 个变异被逮到** |
| 变异自检（集成半场） | `py -3 skills/evals/contract_bridge.py --selftest-loader` | **9/9 个变异被逮到** |
| 交付区可重放检查 | `py -3 skills/evals/contract_bridge_delivery.py` | **8 PASS / 0 FAIL**（exit 0） |
| 变异自检（交付区） | `py -3 skills/evals/contract_bridge_delivery.py --selftest` | **4/4 个变异被逮到** |

退出码约定：`0` 全跑且全过；`1` 有 FAIL；**`2` 无 FAIL 但有 SKIP**（「绿而不完整」——某一半压根没跑）。

> ⚠️ 上面数字是**这张表的字节的函数**。§1 任一文件变动，这些数字即失效，须重跑。

---

## 3. 冻结方法：为什么用 canonical，而不是工作区字节

本仓 `core.autocrlf=true`：**同一份内容，仓库里存 LF，Windows 工作区里存 CRLF**。
于是对「工作区原始字节」算出的哈希，**评委 clone 下来必然对不上** —— 本仓在 2026-09-28 为此空转了**三轮**。

**解法不是去修 `autocrlf`，而是让结论与环境无关**：按 LF 归一后计算。
- `.gitattributes`（`* text=auto eol=lf`）是**保险**；
- canonical 是**根治**：不论检出拿到 LF 还是 CRLF，**算出来是同一个值**。

**实测证据（不是推理）**：把 `contract_bridge_loader.py` **真的改写成 CRLF**（CR 计数 `0 → 642`），
复跑 §4 脚本 —— **仍报「一致」、退出码仍为 0**；再还原为 LF。
⇒ 因此**将来若有人（含 agent）把文件写回 CRLF，本冻结依然有效，不必重冻**。

---

## 4. 怎么自己复现这份冻结

在仓库根目录执行下面这段（**Python，不用 shell** —— shell 的反斜杠在不同环境下会被吞；`sed 's/\r$//'` 一旦丢掉 `\r` 会退化成 `s/r$//`，静默删掉行尾字母）。

```python
# 复现本冻结：任何平台、任何换行检出下结果相同（canonical = LF 归一后计算）
import hashlib, sys
from pathlib import Path
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RECORDED = {
    'skills/evals/contract_bridge.py': '16022f2773d7972b6c73d67023d75ce7a1de49474c69301022cb9d22470c9a7f',
    'skills/evals/contract_bridge_loader.py': '4a8a7098efaf31a62c7c42b1387a77969793d462915ff5a6a90ab1ac707acb7a',
    'skills/evals/contract_bridge_delivery.py': '7f5a376afe0fa1809e6c10bb0e7f61ce3b3ec66803f0ffd71cb9d092e8de5f4f',
    'docs/agents/mes-bridge-contract.md': '0ecc7b8d81765468f0dfc1bf8ba3b987b2697788005fbe7997b6e405d16b4043',
    'docs/mes-demo/index.html': '66cb46f674a37e741344d4f02ca98be8afe60b39013c6494fbda3fe8a13fc0db',
    'docs/mes-demo/mes-data/inbox.json': 'd6ab9fbdb39c6920206542c35115989142cf581a997b23189fb82626214269bd',
    'docs/mes-demo/mes-data/xj-records.json': 'b42a41b8d3ef20238456b8eb42cfbb551eb18160d1967a208592932ac1098b66',
    'skills/mes-inspection-intake/scripts/commit.py': 'eccc79ac56ba71d43dd6c5dd806d9c3158c2209187044cc3c30eba9cb706ec6a',
    'skills/mes-inspection-intake/scripts/intake_core.py': '07740f5b13e46abda46fd04613036d341e6ba96ee8c1f5105751dd8e7f4fd858',
    'skills/mes-inspection-intake/evals/fixtures/finding-demo.json': '6e5bbd8dac2e3168d6a08b3700ea2636b8ae1762114e20bd74601a7c182440e5',
}

def canon(p):
    raw = Path(p).read_bytes()
    return hashlib.sha256(raw.replace(bytes([13, 10]), bytes([10]))).hexdigest()

bad = 0
for f, want in RECORDED.items():
    got = canon(f)
    ok = got == want
    bad += not ok
    print(('OK   ' if ok else '不同 ') + got + '  ' + f)
    if not ok:
        print('       记录值 ' + want)
print()
print('✅ 与封版记录一致' if not bad else f'❌ {bad} 个文件与记录不一致')
sys.exit(1 if bad else 0)
```

**实测输出**（在本次冻结的字节上跑出，退出码 0）：

```text
OK   16022f2773d7972b6c73d67023d75ce7a1de49474c69301022cb9d22470c9a7f  skills/evals/contract_bridge.py
OK   4a8a7098efaf31a62c7c42b1387a77969793d462915ff5a6a90ab1ac707acb7a  skills/evals/contract_bridge_loader.py
OK   7f5a376afe0fa1809e6c10bb0e7f61ce3b3ec66803f0ffd71cb9d092e8de5f4f  skills/evals/contract_bridge_delivery.py
OK   0ecc7b8d81765468f0dfc1bf8ba3b987b2697788005fbe7997b6e405d16b4043  docs/agents/mes-bridge-contract.md
OK   66cb46f674a37e741344d4f02ca98be8afe60b39013c6494fbda3fe8a13fc0db  docs/mes-demo/index.html
OK   d6ab9fbdb39c6920206542c35115989142cf581a997b23189fb82626214269bd  docs/mes-demo/mes-data/inbox.json
OK   b42a41b8d3ef20238456b8eb42cfbb551eb18160d1967a208592932ac1098b66  docs/mes-demo/mes-data/xj-records.json
OK   eccc79ac56ba71d43dd6c5dd806d9c3158c2209187044cc3c30eba9cb706ec6a  skills/mes-inspection-intake/scripts/commit.py
OK   07740f5b13e46abda46fd04613036d341e6ba96ee8c1f5105751dd8e7f4fd858  skills/mes-inspection-intake/scripts/intake_core.py
OK   6e5bbd8dac2e3168d6a08b3700ea2636b8ae1762114e20bd74601a7c182440e5  skills/mes-inspection-intake/evals/fixtures/finding-demo.json

✅ 与封版记录一致
```

判据：**退出码 0 = 与封版记录一致**。任何一个文件不同，脚本会打印两行（实算值与记录值）并以 1 退出。

---

## 5. 这份记录**不**声称什么

如实划界，避免被读成比它更强的东西：

- **不声称产物「由流水线产出」**。文件名与 schema 都证明不了谁写的。
  来源由 `contract_bridge_delivery.py` 的 **D6（复现：除 `produced_at` 外逐字节相同）** 判定，
  那才是契约认可的**唯一**手段。
- **`produced_at ↔ mtime` 不是来源判据**。Δ≈0 证明不了「非手写」；而任何 checkout/clone 都会重置 mtime，
  使 Δ 必然变大 —— **那不代表倒填**。故该值在门里只作**本机参考**，不下判定。
  （一条在评委机器上**必然报警**的门，与一条永远红的门同类：都会被训练成「不当回事」。）
- **门只覆盖它实际加载的东西**。集成半场会起浏览器、走真实 DOM；
  交付区检查会**自己起只读服务**并比对 `served == 磁盘`，而不是引用「某人口中的服务地址」。
