"""
implied_erp.py —— 市場隱含股權風險溢價
=========================================================
基本面 ERP 是「我們認為市場應該要求多少補償」；
隱含 ERP 是「市場現在實際要求多少補償」。兩者相減，就是情緒刻度。

兩種反推方式（同時輸出，互為交叉檢核）：

  1. 股利增長法（Gordon）
         re = D/P + g   →   ERP_implied = 股息率 + 長期增長 − rf
     優點：直接對應「投資人要求的回報」；缺點：對 g 的假設敏感。

  2. 盈利收益率法（零增長下界）
         ERP_implied = E/P − rf = 1/PE − rf
     優點：不需要增長假設；缺點：忽略成長，通常是偏低的下界。

判讀：
    implied − fundamental > +1pp  → 市場要求更高補償，情緒偏謹慎（估值相對保守）
    implied − fundamental < −1pp  → 市場要求更低補償，情緒偏樂觀（估值相對進取）
    其餘                          → 中性

本模組不預測指數點位，只把「市場定價 vs 基本面」的落差量化，
供 DCF 的安全邊際與診斷文字使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SENTIMENT_LABEL = {
    "cautious": "偏謹慎",
    "neutral": "中性",
    "optimistic": "偏樂觀",
}


@dataclass
class ImpliedErpResult:
    available: bool
    method: str = "gordon"
    implied: Optional[float] = None
    fundamental: Optional[float] = None
    difference: Optional[float] = None
    sentiment: str = "neutral"
    sentiment_label: str = "中性"
    gordon: Optional[float] = None
    earnings_yield: Optional[float] = None
    pe: Optional[float] = None
    div_yield: Optional[float] = None
    growth: Optional[float] = None
    rf: Optional[float] = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "implied_erp": self.implied,
            "fundamental_erp": self.fundamental,
            "difference": self.difference,
            "sentiment": self.sentiment,
            "sentiment_label": self.sentiment_label,
            "gordon_erp": self.gordon,
            "earnings_yield_erp": self.earnings_yield,
            "hsi_pe": self.pe,
            "hsi_div_yield": self.div_yield,
            "growth": self.growth,
        }


def implied_erp(
    rf: float,
    fundamental: float,
    pe: Optional[float] = None,
    div_yield: Optional[float] = None,
    growth: float = 0.04,
    tolerance: float = 0.010,
) -> ImpliedErpResult:
    if rf is None or fundamental is None:
        return ImpliedErpResult(available=False, note="缺少 rf 或基本面 ERP")

    gordon = None
    if div_yield is not None and div_yield > 0:
        gordon = div_yield + growth - rf

    earnings = None
    if pe is not None and pe > 0:
        earnings = 1.0 / pe - rf

    primary = gordon if gordon is not None else earnings
    if primary is None:
        return ImpliedErpResult(
            available=False, fundamental=fundamental, rf=rf,
            note="缺少 HSI 市盈率或股息率，無法反推隱含 ERP",
        )

    diff = primary - fundamental
    if diff > tolerance:
        sentiment = "cautious"
    elif diff < -tolerance:
        sentiment = "optimistic"
    else:
        sentiment = "neutral"

    method = "gordon" if gordon is not None else "earnings_yield"
    note = (f"{'股利增長法' if method == 'gordon' else '盈利收益率法'}："
            f"{primary:.2%}；基本面 {fundamental:.2%}；差 {diff * 100:+.2f}pp")
    if gordon is not None and earnings is not None:
        note += f"；交叉檢核 E/P 法 {earnings:.2%}"

    return ImpliedErpResult(
        available=True,
        method=method,
        implied=primary,
        fundamental=fundamental,
        difference=diff,
        sentiment=sentiment,
        sentiment_label=SENTIMENT_LABEL[sentiment],
        gordon=gordon,
        earnings_yield=earnings,
        pe=pe,
        div_yield=div_yield,
        growth=growth,
        rf=rf,
        note=note,
    )
