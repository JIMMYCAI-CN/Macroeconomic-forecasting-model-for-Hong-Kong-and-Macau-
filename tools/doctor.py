#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/doctor.py —— 仓库完整性自检

用途：在补齐缺失模块前后，快速判断当前仓库到底缺什么、缺在哪个符号上。
     全部使用 Python 标准库，不依赖任何第三方包。

用法：
    python tools/doctor.py            # 完整自检
    python tools/doctor.py --quiet    # 只输出失败项
    python tools/doctor.py --smoke    # 额外尝试运行 run_macro.py --show-thresholds

退出码：0 = 全部通过，1 = 存在缺失
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

try:  # Windows 控制台默认 cp936，避免中文输出抛 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 期望结构
# 每个条目：路径 -> 该模块必须能提供的公开符号
REQUIRED = {
    "macro_engine/__init__.py": ["EngineConfig", "build_bundle", "compute", "FirmInputs"],
    "macro_engine/config.py": ["EngineConfig", "DcfConfig", "NpvConfig", "RegionProfile"],
    "macro_engine/models.py": [
        "Observation", "MacroInputs", "MarketInputs", "ChinaInputs", "FirmInputs", "STAGE_LABEL",
    ],
    "macro_engine/net.py": [
        "CACHE_DIR", "DataSourceError", "download", "fetch_json", "fetch_text",
        "now_stamp", "read_cache", "write_cache",
    ],
    "macro_engine/engine.py": ["compute", "erp_decomposition", "DataBundle", "RegionResult"],
    "macro_engine/analytics/__init__.py": [
        "altman", "credit", "dcf", "hp", "implied_erp", "liquidity",
        "npv", "ppp", "risk", "taylor", "volatility", "wacc",
    ],
    "macro_engine/cli.py": ["main", "parse_rate"],
    "macro_engine/report.py": ["to_dict"],
    "macro_engine/history.py": ["SnapshotStore"],
    "macro_engine/cycle.py": [],
    "macro_engine/capm.py": [],
    "macro_engine/excel_export.py": [],
    "macro_engine/diagnosis.py": [],
    "macro_engine/gui.py": [],
    "macro_engine/sources/__init__.py": [],
    "macro_engine/sources/censtatd.py": [],
    "macro_engine/sources/hkma.py": [],
    "macro_engine/sources/dsec.py": [],
    "macro_engine/sources/market.py": [],
    "macro_engine/sources/hibor.py": [],
    "macro_engine/sources/cn_macro.py": [],
    "macro_engine/analytics/hp.py": [],
    "macro_engine/analytics/taylor.py": [],
    "macro_engine/analytics/credit.py": [],
    "macro_engine/analytics/liquidity.py": [],
    "macro_engine/analytics/implied_erp.py": [],
    "macro_engine/analytics/volatility.py": [],
    "macro_engine/analytics/altman.py": [],
    "macro_engine/analytics/ppp.py": [],
    "macro_engine/analytics/risk.py": [],
    "macro_engine/analytics/wacc.py": [],
    "macro_engine/analytics/dcf.py": [],
    "macro_engine/analytics/npv.py": [],
}

# 根目录扁平文件 -> 真实归属（网页上传丢失目录层级的历史遗留）
FLAT_TO_PACKAGE = {
    "__init__.py": "macro_engine/sources/__init__.py",
    "censtatd.py": "macro_engine/sources/censtatd.py",
    "hkma.py": "macro_engine/sources/hkma.py",
    "dsec.py": "macro_engine/sources/dsec.py",
    "market.py": "macro_engine/sources/market.py",
    "hibor.py": "macro_engine/sources/hibor.py",
    "cn_macro.py": "macro_engine/sources/cn_macro.py",
    "hp.py": "macro_engine/analytics/hp.py",
    "taylor.py": "macro_engine/analytics/taylor.py",
    "credit.py": "macro_engine/analytics/credit.py",
    "liquidity.py": "macro_engine/analytics/liquidity.py",
    "implied_erp.py": "macro_engine/analytics/implied_erp.py",
    "volatility.py": "macro_engine/analytics/volatility.py",
    "altman.py": "macro_engine/analytics/altman.py",
    "ppp.py": "macro_engine/analytics/ppp.py",
    "risk.py": "macro_engine/analytics/risk.py",
    "wacc.py": "macro_engine/analytics/wacc.py",
    "dcf.py": "macro_engine/analytics/dcf.py",
    "npv.py": "macro_engine/analytics/npv.py",
}

PASS, FAIL, WARN = "[ OK ]", "[FAIL]", "[WARN]"


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def check_layout(quiet: bool) -> list:
    """检查文件位置：是否还是扁平结构。"""
    problems = []
    if not quiet:
        print("== 1. 目录布局 ==")
    has_pkg = (ROOT / "macro_engine").is_dir()
    if has_pkg:
        print(f"{PASS} macro_engine/ 包目录存在")
    else:
        print(f"{FAIL} macro_engine/ 包目录不存在 —— run_macro.py 必然 ModuleNotFoundError")
        problems.append("macro_engine/ 缺失")

    stray = [f for f in FLAT_TO_PACKAGE if (ROOT / f).is_file()]
    if stray:
        print(f"{FAIL} 根目录残留 {len(stray)} 个扁平模块（应位于子包内）")
        for f in sorted(stray):
            print(f"         {f}  ->  {FLAT_TO_PACKAGE[f]}")
        problems.append("根目录扁平模块未归位")
    else:
        print(f"{PASS} 根目录没有残留的扁平模块")
    return problems


def check_files(quiet: bool) -> list:
    problems = []
    if not quiet:
        print("\n== 2. 必需文件 ==")
    missing = [p for p in REQUIRED if not (ROOT / p).is_file()]
    if not missing:
        print(f"{PASS} 全部 {len(REQUIRED)} 个文件就位")
        return problems
    print(f"{FAIL} 缺失 {len(missing)} / {len(REQUIRED)} 个文件")
    for p in missing:
        print(f"         {p}")
    problems.append(f"缺失 {len(missing)} 个文件")
    return problems


def check_structure_only() -> bool:
    return (ROOT / "macro_engine").is_dir()


def check_imports(quiet: bool) -> list:
    """逐个真实 import，定位到符号级别。"""
    problems = []
    if not quiet:
        print("\n== 3. 符号可用性（真实 import）==")
    if not check_structure_only():
        print(f"{WARN} 包目录不存在，跳过符号检查")
        return problems

    sys.path.insert(0, str(ROOT))
    bad = 0
    for mod_path, symbols in REQUIRED.items():
        if not mod_path.endswith("__init__.py") and not (ROOT / mod_path).is_file():
            continue
        if not symbols:
            continue
        modname = mod_path[:-3].replace("/", ".").replace(".__init__", "")
        try:
            mod = __import__(modname, fromlist=["*"])
        except Exception as exc:  # noqa: BLE001
            print(f"{FAIL} import {modname}  ({type(exc).__name__}: {exc})")
            bad += 1
            continue
        gone = [s for s in symbols if not hasattr(mod, s)]
        if gone:
            print(f"{FAIL} {modname} 缺少符号: {', '.join(gone)}")
            bad += 1
        else:
            print(f"{PASS} {modname} ({len(symbols)} 个符号齐全)")
    if bad:
        problems.append(f"{bad} 个模块不可用")
    return problems


def check_entry(quiet: bool) -> list:
    """跑一次真实入口，抓 traceback 最后一行。"""
    problems = []
    if not quiet:
        print("\n== 4. 入口冒烟 ==")
    entry = ROOT / "run_macro.py"
    if not entry.is_file():
        print(f"{FAIL} run_macro.py 不存在")
        problems.append("run_macro.py 缺失")
        return problems
    proc = subprocess.run(
        [sys.executable, "-c", "import macro_engine.cli"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode == 0:
        print(f"{PASS} import macro_engine.cli 成功")
    else:
        tail = (proc.stderr or "").strip().splitlines()
        print(f"{FAIL} import macro_engine.cli 失败: {tail[-1] if tail else '未知错误'}")
        problems.append("cli 不可导入")
    return problems


def run_smoke(quiet: bool) -> list:
    if not quiet:
        print("\n== 5. 计算冒烟（--offline）==")
    proc = subprocess.run(
        [sys.executable, "run_macro.py", "--offline", "--show-thresholds"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    if proc.returncode == 0:
        print(f"{PASS} 离线计算通过（输出 {len(proc.stdout.splitlines())} 行）")
        return []
    tail = (proc.stderr or "").strip().splitlines()
    print(f"{FAIL} 离线计算失败: {tail[-1] if tail else '未知错误'}")
    return ["离线计算失败"]


def main() -> int:
    ap = argparse.ArgumentParser(description="仓库完整性自检")
    ap.add_argument("--quiet", action="store_true", help="只输出失败项")
    ap.add_argument("--smoke", action="store_true", help="额外跑一次离线计算")
    args = ap.parse_args()

    print(f"仓库根目录: {ROOT}\n")
    problems = []
    problems += check_layout(args.quiet)
    problems += check_files(args.quiet)
    problems += check_imports(args.quiet)
    problems += check_entry(args.quiet)
    if args.smoke:
        problems += run_smoke(args.quiet)

    print("\n" + "=" * 60)
    if problems:
        print(f"结论: 仓库不完整（{len(problems)} 类问题）")
        print("修复清单见 MISSING_MODULES.md；补齐后重跑本脚本验收。")
        return 1
    print("结论: 结构完整，入口可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
