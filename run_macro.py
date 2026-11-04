#!/usr/bin/env python3
"""
run_macro.py —— 港澳宏觀折現率計算引擎（入口）
=========================================================
    python run_macro.py                     # 港澳一次算完
    python run_macro.py --region HK
    python run_macro.py --json out.json --csv out.csv
    python run_macro.py --show-thresholds

詳細參數見 --help。
"""

from macro_engine.cli import main

if __name__ == "__main__":
    main()
