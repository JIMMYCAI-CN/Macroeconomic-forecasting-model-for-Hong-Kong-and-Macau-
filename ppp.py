"""
ppp.py —— HKD/CNY 購買力平價與錯配幅度
=========================================================
大量港股的收入以人民幣計價，但估值以港元折現。匯率不是「背景變數」，
而是直接影響換算後現金流的因子。

相對 PPP 的做法：
    均衡匯率 E* = E_base × (1 + 累計 HK 通脹) / (1 + 累計內地通脹)
    E = HKD per CNY（例如 0.85 代表 1 人民幣兌 0.85 港元）

  * 若 E_spot > E*：港元偏弱（要更多港元換 1 人民幣）
  * 若 E_spot < E*：港元偏強 → 內地收入換算回港元時縮水，對港股不利

錨（E_base 與基準期）放在 RegionProfile，可由設定檔修改。
這不是預測匯率走勢，而是給 DCF 一個「匯率目前偏離購買力多少」的刻度，
供毛利率與增長假設的敏感度分析使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


def _month_index(period: str) -> Optional[int]:
    text = str(period)
    if len(text) < 7 or text[4] != "-":
        return None
    try:
        return int(text[:4]) * 12 + int(text[5:7])
    except ValueError:
        return None


def cumulative_inflation(
    series: Sequence[Tuple[str, float]], base_period: str
) -> Optional[float]:
    """
    由月度「同比」序列重建物價指數，再算 base_period 之後的累計漲幅。

    同比是相對去年同月的變化，不能當成月度環比連乘（會把 1.7% 的年通脹
    算成 22%）。做法是以基準期為錨：
      * base_period 前 12 個月設為同一水平（缺少年內路徑資訊，只能如此假設）；
      * 之後逐月用 L_t = L_{t−12} × (1 + yoy_t) 精確鏈接。
    由於只關心「基準期之後」的累計漲幅，初始 12 個月的平坦假設
    只帶來一次性的小誤差，不會像逐月連乘那樣逐年放大。
    """
    yoy: dict = {}
    for period, value in series:
        idx = _month_index(period)
        if idx is None or value is None:
            continue
        yoy[idx] = float(value)
    if not yoy:
        return None

    base_idx = _month_index(base_period)
    if base_idx is None or base_idx not in yoy:
        return None
    if any(i not in yoy for i in range(base_idx - 11, max(yoy) + 1)):
        return None

    levels = {i: 100.0 for i in range(base_idx - 11, base_idx + 1)}
    for idx in range(base_idx + 1, max(yoy) + 1):
        prev = levels.get(idx - 12)
        if prev is None:
            return None
        levels[idx] = prev * (1.0 + yoy[idx])
    return levels[max(yoy)] / 100.0 - 1.0


@dataclass
class PppResult:
    available: bool
    spot: Optional[float] = None
    fair: Optional[float] = None
    misalignment: Optional[float] = None     # spot/fair − 1
    label: str = "—"
    base_rate: Optional[float] = None
    base_period: str = ""
    hk_cum: Optional[float] = None
    cn_cum: Optional[float] = None
    translation_impact: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "spot": self.spot, "fair": self.fair,
            "misalignment": self.misalignment,
            "label": self.label,
            "base_rate": self.base_rate, "base_period": self.base_period,
            "hk_cum_inflation": self.hk_cum, "cn_cum_inflation": self.cn_cum,
        }


def ppp_misalignment(
    spot: Optional[float],
    base_rate: float,
    base_period: str,
    hk_cpi_series: Sequence[Tuple[str, float]],
    cn_cpi_series: Sequence[Tuple[str, float]],
    threshold: float = 0.05,
) -> PppResult:
    if spot is None or spot <= 0:
        return PppResult(available=False, base_rate=base_rate,
                         base_period=base_period, note="缺少 HKD/CNY 即期匯率")

    hk_cum = cumulative_inflation(hk_cpi_series, base_period)
    cn_cum = cumulative_inflation(cn_cpi_series, base_period)
    if hk_cum is None or cn_cum is None:
        return PppResult(
            available=False, spot=spot, base_rate=base_rate,
            base_period=base_period, hk_cum=hk_cum, cn_cum=cn_cum,
            note="CPI 歷史不足，無法建立 PPP 均衡匯率",
        )

    fair = base_rate * (1.0 + hk_cum) / (1.0 + cn_cum)
    mis = spot / fair - 1.0

    if mis < -threshold:
        label = "港元偏強"
        impact = "內地收入換算回港元縮水，對內地收入型港股構成逆風"
    elif mis > threshold:
        label = "港元偏弱"
        impact = "內地收入換算回港元有匯兌助力"
    else:
        label = "接近均衡"
        impact = "匯率錯配在容忍區間內"

    return PppResult(
        available=True,
        spot=spot,
        fair=fair,
        misalignment=mis,
        label=label,
        base_rate=base_rate,
        base_period=base_period,
        hk_cum=hk_cum,
        cn_cum=cn_cum,
        translation_impact=impact,
        note=(f"錨 {base_rate:.4f} @ {base_period}；累計通脹 HK {hk_cum:+.2%}、"
              f"內地 {cn_cum:+.2%} → 均衡 {fair:.4f}；即期 {spot:.4f}（{mis * 100:+.1f}%）"),
    )
