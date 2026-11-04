"""
wacc.py —— 加權平均資本成本（DCF 與 NPV 共用的核心折現率）
=========================================================
    rd    = rf + 信用利差（＋企業專屬溢價，若啟用 Altman）
    re    = rf + β × 調整後 ERP（＋企業專屬溢價）
    WACC  = E/(D+E)·re + D/(D+E)·rd·(1 − t)
    實質  = (1 + 名義) / (1 + π) − 1      ← 費雪精確式

兩個容易被忽略的細節：
  1. D/E 是「債務／股權」，不是「債務／總資產」。本模組接受 D/E，
     再換算成權重，避免使用者直接填 40% 卻被當成 40% 負債比。
  2. 稅盾只用於債務成本；把稅盾套在 re 上是常見的公式錯誤。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class WaccResult:
    available: bool
    re_nominal: float = 0.0
    re_real: float = 0.0
    rd_nominal: float = 0.0
    rd_real: float = 0.0
    tax: float = 0.0
    debt_to_equity: float = 0.0
    debt_weight: float = 0.0
    equity_weight: float = 0.0
    spread: float = 0.0
    wacc_nominal: float = 0.0
    wacc_real: float = 0.0
    cpi: float = 0.0
    warning: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "re_nominal": self.re_nominal, "re_real": self.re_real,
            "rd_nominal": self.rd_nominal, "rd_real": self.rd_real,
            "tax": self.tax, "debt_to_equity": self.debt_to_equity,
            "debt_weight": self.debt_weight, "equity_weight": self.equity_weight,
            "credit_spread": self.spread,
            "wacc_nominal": self.wacc_nominal, "wacc_real": self.wacc_real,
        }


def build_wacc(
    re_nominal: float,
    rf: float,
    spread: float,
    cpi: float,
    tax: float,
    debt_to_equity: float,
    band: Optional[tuple[float, float]] = None,
) -> WaccResult:
    if debt_to_equity < 0:
        raise ValueError("D/E 不可為負數")
    if not (0.0 <= tax < 1.0):
        raise ValueError("有效稅率必須介於 0–100%")

    debt_weight = debt_to_equity / (1.0 + debt_to_equity) if debt_to_equity else 0.0
    equity_weight = 1.0 - debt_weight
    rd = rf + spread

    wacc = equity_weight * re_nominal + debt_weight * rd * (1.0 - tax)
    rd_real = (1.0 + rd) / (1.0 + cpi) - 1.0 if cpi > -1 else rd
    wacc_real = (1.0 + wacc) / (1.0 + cpi) - 1.0 if cpi > -1 else wacc

    warning = ""
    if band and not (band[0] <= wacc <= band[1]):
        warning = (f"WACC {wacc:.2%} 超出警戒區間 {band[0]:.1%}–{band[1]:.1%}，"
                   "請檢查 β、ERP、D/E 或信用利差假設")

    return WaccResult(
        available=True,
        re_nominal=re_nominal,
        re_real=(1.0 + re_nominal) / (1.0 + cpi) - 1.0 if cpi > -1 else re_nominal,
        rd_nominal=rd,
        rd_real=rd_real,
        tax=tax,
        debt_to_equity=debt_to_equity,
        debt_weight=debt_weight,
        equity_weight=equity_weight,
        spread=spread,
        wacc_nominal=wacc,
        wacc_real=wacc_real,
        cpi=cpi,
        warning=warning,
        note=(f"{equity_weight:.0%}×{re_nominal:.2%} + "
              f"{debt_weight:.0%}×{rd:.2%}×(1−{tax:.1%}) = {wacc:.2%}"),
    )
