# 仓库完整性诊断与修复契约

> 本文档由协作者 `leo63772558` 在排查后生成。目的：把「仓库结构不一致」这个模糊描述，变成一份**可逐条核对、可直接补齐**的清单。
> 生成时间：2026-11-11

---

## 一、结论

**当前 `main` 分支不是「结构不一致」，而是「核心代码缺失」。**

运行入口直接失败：

```text
$ python run_macro.py
Traceback (most recent call last):
  File "run_macro.py", line 13, in <module>
    from macro_engine.cli import main
ModuleNotFoundError: No module named 'macro_engine'
```

`run_macro.py` 只有 16 行，全部逻辑都在 `macro_engine` 包里，而这个包**在仓库中完全不存在**。
README 第 8 节「模組結構」列出的 13 个核心模块、2 个子包，一个都没有提交上去。

也就是说：**任何人 clone 这个仓库，都无法运行、无法测试、无法复现 README 里的任何一条命令。**

---

## 二、已提交的文件实际是什么

仓库根目录有 19 个 `.py`，但它们**不是根目录模块，而是两个子包的内容被拍平（flatten）到了根目录**。证据是它们内部使用 `from ..xxx import` 这种**包内相对导入**，只有位于子包中才合法：

| 根目录文件 | 真实归属 | 证据 |
|---|---|---|
| `__init__.py` | `macro_engine/sources/__init__.py` | 内容是「資料源子套件：每個官方機構一個模組」（92 字节，非包入口） |
| `censtatd.py` `hkma.py` `dsec.py` `market.py` `hibor.py` `cn_macro.py` | `macro_engine/sources/` | `from ..models import Observation` / `from ..net import ...` |
| `hp.py` `taylor.py` `credit.py` `liquidity.py` `implied_erp.py` `volatility.py` `altman.py` `ppp.py` `risk.py` `wacc.py` `dcf.py` `npv.py` | `macro_engine/analytics/` | `from ..config import DcfConfig, RegionProfile` 等 |

这与提交历史一致：`Create macro_engine` → `Delete macro_engine` → `Add files via upload`（网页上传时丢失了目录层级）。

---

## 三、缺失清单（必须补齐）

### 3.1 核心模块（12 个）

| 模块 | 必须提供的符号 | 证据来源 |
|---|---|---|
| `macro_engine/__init__.py` | `EngineConfig` `build_bundle` `compute` `FirmInputs`（README 公开 API）、`__version__` | README §2、README §8 |
| `macro_engine/config.py` | `EngineConfig` `DcfConfig` `NpvConfig` `RegionProfile` | `dcf.py` `npv.py`、`tests` 第 253 行 |
| `macro_engine/models.py` | `Observation` `MacroInputs` `MarketInputs` `ChinaInputs` `FirmInputs` `STAGE_LABEL` | `tests` 第 256 行、6 个 sources 模块 |
| `macro_engine/net.py` | `CACHE_DIR` `DataSourceError` `download` `fetch_json` `fetch_text` `now_stamp` `read_cache` `write_cache` | `hkma.py` 第 30–37 行、`censtatd.py` 等 5 个模块 |
| `macro_engine/engine.py` | `compute` `erp_decomposition` `DataBundle` `RegionResult` | `tests` 第 254/629 行 |
| `macro_engine/analytics/__init__.py` | 暴露 `altman credit dcf hp implied_erp liquidity npv ppp risk taylor volatility wacc` | `tests` 第 245–252 行 |
| `macro_engine/cli.py` | `main` `parse_rate` | `run_macro.py`、`tests` 第 22 行 |
| `macro_engine/report.py` | `to_dict` | `tests` 第 23 行 |
| `macro_engine/history.py` | `SnapshotStore` | `tests` 第 255 行 |
| `macro_engine/cycle.py` | 港澳门檻、判定轨迹（`tests` 通过 `from macro_engine import capm, cycle` 使用） | `tests` 第 21 行 |
| `macro_engine/capm.py` | CAPM + 费雪实质化 | `tests` 第 21 行 |
| `macro_engine/excel_export.py` | 10 工作表导出 | `tests` 第 722 行 |
| `macro_engine/diagnosis.py` | 自动诊断文字（README §8 列出） | README §8 |
| `macro_engine/gui.py` | 七页签图形界面（README §6） | README §6、`start_gui.bat` |

### 3.2 `sources/__init__.py` 与 `analytics/__init__.py`

两个子包的 `__init__.py` 都要提交（`sources/__init__.py` 已有内容但被放错位置；`analytics/__init__.py` 完全缺失）。

---

## 四、修复后的目标结构

```text
run_macro.py                     ← 已存在（16 行，不用改）
requirements.txt                 ← 已存在
README.md                        ← 已存在
start_gui.bat  start_macro.bat   ← 已存在
macro_engine/
  __init__.py                    ← 缺失：公开 API 出口
  config.py                      ← 缺失
  models.py                      ← 缺失
  net.py                         ← 缺失
  engine.py                      ← 缺失
  cli.py                         ← 缺失
  gui.py                         ← 缺失
  report.py                      ← 缺失
  history.py                     ← 缺失
  diagnosis.py                   ← 缺失
  cycle.py                       ← 缺失
  capm.py                        ← 缺失
  excel_export.py                ← 缺失
  sources/
    __init__.py                  ← 根目录的 __init__.py 需要移到这里
    censtatd.py hkma.py dsec.py market.py hibor.py cn_macro.py   ← 需要从根目录移入
  analytics/
    __init__.py                  ← 缺失
    hp.py taylor.py credit.py liquidity.py implied_erp.py volatility.py
    altman.py ppp.py risk.py wacc.py dcf.py npv.py               ← 需要从根目录移入
tests/
  test_macro.py                  ← 已存在（46 测试 / 180 断言，可作为验收标准）
output/                          ← 已存在（示例导出物）
```

---

## 五、验收标准

补齐后必须同时满足：

```bash
python run_macro.py --help            # 不报 ModuleNotFoundError
python run_macro.py --offline         # 离线可算完港澳
python run_macro.py --show-thresholds # 打印港澳两套门槛
python tests/test_macro.py            # 46 个测试 / 180 个断言全部通过
python run_macro.py --gui             # 七页签界面可打开
```

任何一项失败，说明补齐不完整。可直接用仓库自带的自检脚本定位：

```bash
python tools/doctor.py
```

---

## 六、为什么没有直接「移动文件了事」

只把 19 个扁平文件按上表移回子包**并不能让项目跑起来**——因为 `config.py` `models.py` `net.py` `engine.py` 这些被依赖的模块一个都不存在，移动后只会从 `ModuleNotFoundError: macro_engine` 变成 `ImportError: attempted relative import with no known parent package`。

核心代码只存在于项目作者本地（本机全盘搜索 `macro_engine` 目录与 `def build_bundle` 均无结果）。

**因此需要作者提供缺失的 13 个文件。** 拿到后按第四节结构放置，用 `tools/doctor.py` 验证即可。
