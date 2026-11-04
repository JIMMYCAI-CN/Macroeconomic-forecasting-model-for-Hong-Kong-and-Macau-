"""
npv.py —— NPV 專用參數（服務資本項目評估）
=========================================================
標準 NPV 分支與股票市場情緒隔離：
  * 不使用永續增長假設；
  * 不讀取 VIX、隱含 ERP、Z-Score、PPP 匯率因子；
  * 只用「宏觀週期 + 綜合風險分數」調整項目要求回報率。

這是刻意的方法論選擇：一個工廠的可行性不應該因為恒指當天跌 3% 而改變。
只有當使用者手動打開「實物期權通道」時，才允許市場波動率與情緒因子
流入 NPV 分支，用來支援 Real Option 的波動率輸入。

    乘數 = 1 + risk_sensitivity × (風險分數/100) + 週期加成
    門檻 = WACC × 乘數 + 項目專屬溢價
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import NpvConfig


@dataclass
class NpvParams:
    available: bool = True
    multiplier: float = 1.0
    hurdle: float = 0.0
    wacc: float = 0.0
    project_premium: float = 0.0
    cycle_key: str = ""
    cycle_add: float = 0.0
    risk_score: float = 0.0
    real_option: bool = False
    option_adjust: float = 0.0
    option_volatility: Optional[float] = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "risk_multiplier": self.multiplier,
            "hurdle_rate": self.hurdle,
            "wacc": self.wacc,
            "project_premium": self.project_premium,
            "cycle_add": self.cycle_add,
            "real_option_enabled": self.real_option,
            "real_option_adjust": self.option_adjust,
            "project_volatility": self.option_volatility,
        }


def build_npv_params(
    wacc: float,
    risk_score: float,
    cycle_key: str,
    cfg: NpvConfig,
    real_option: bool = False,
    sigma: Optional[float] = None,
    sentiment: Optional[str] = None,
) -> NpvParams:
    cycle_add = cfg.cycle_add.get(cycle_key, 0.0)
    multiplier = 1.0 + cfg.risk_sensitivity * (risk_score / 100.0) + cycle_add
    multiplier = max(cfg.minimum, min(cfg.maximum, multiplier))

    option_adjust = 0.0
    note = (f"乘數 = 1 + {cfg.risk_sensitivity:.2f}×{risk_score / 100:.2f}"
            f" + 週期 {cycle_add:+.2f} = {multiplier:.2f}")
    if real_option:
        # 只有開啟通道時，市場波動率與情緒才允許進入 NPV
        if sigma is not None:
            option_adjust += max(0.0, sigma - 0.25) * 0.20
        if sentiment == "cautious":
            option_adjust += 0.0020
        elif sentiment == "optimistic":
            option_adjust -= 0.0010
        option_adjust = max(-0.010, min(0.020, option_adjust))
        note += f"；實物期權通道 +{option_adjust * 100:.2f}pp（σ/情緒）"
    else:
        note += "；標準 NPV：不讀取 VIX／隱含 ERP／Z-Score／PPP"

    hurdle = wacc * multiplier + cfg.project_premium + option_adjust
    return NpvParams(
        available=True,
        multiplier=multiplier,
        hurdle=hurdle,
        wacc=wacc,
        project_premium=cfg.project_premium,
        cycle_key=cycle_key,
        cycle_add=cycle_add,
        risk_score=risk_score,
        real_option=real_option,
        option_adjust=option_adjust,
        option_volatility=sigma if real_option else None,
        note=note,
    )
