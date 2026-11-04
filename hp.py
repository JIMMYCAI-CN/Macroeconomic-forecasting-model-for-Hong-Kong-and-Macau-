"""
hp.py —— Hodrick-Prescott 濾波與 GDP 缺口
=========================================================
為什麼一定要有 GDP 缺口，而不能只看 GDP 同比？
  * 同比增長 3% 對香港可能只是「回到趨勢」，對澳門卻可能是深度衰退
    （澳門趨勢增速接近 3%，且波動極大）。缺口把「增長」換成「相對潛在水平」，
    週期判定與 ERP 調整才有共同的量尺。

資料處理的關鍵一步：
  官方 API 給的是「實質同比」而不是實質 GDP 水平。本模組用
  L_t = L_{t−4} × (1 + yoy_t) 逐年鏈接，重建一個實質 GDP 指數。
  HP 濾波關心的是「相對趨勢的偏離」，指數的基準值不影響缺口，
  所以這個重建對缺口計算是有效的；但序列最開頭幾季會受初始值假設影響，
  因此預設丟棄前 8 季（drop_head）再濾波。

HP 濾波本身用共軛梯度法解 (I + λK′K)τ = y。
純標準庫、O(n) 記憶體，150 季的序列在毫秒級完成。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

#: 季度數據的慣用平滑參數（Ravn & Uhlig 建議值）
DEFAULT_LAMBDA = 1600.0


def _quarter_index(period: str) -> Optional[int]:
    """'2026Q2' → 8106；'2026-06'（季度末月）→ 也支援。"""
    text = str(period).strip()
    if "Q" in text.upper():
        year, _, q = text.upper().partition("Q")
        try:
            return int(year) * 4 + int(q)
        except ValueError:
            return None
    if "-" in text:
        parts = text.split("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            month = int(parts[1])
            return int(parts[0]) * 4 + (month - 1) // 3 + 1
    if len(text) == 6 and text.isdigit():      # 202606
        month = int(text[4:])
        return int(text[:4]) * 4 + (month - 1) // 3 + 1
    return None


def chain_yoy(series: Sequence[Tuple[str, float]]) -> Tuple[List[Tuple[str, float]], int]:
    """
    把季度實質同比鏈接成水平指數（最後一期不設錨，只影響水平、不影響缺口）。

    同步數據只有「相對去年同季」的變化，無法還原第一年的年內水平路徑。
    本函式假設第一年按第一個觀測同比的等效季增速平滑增長，
    之後逐季用 L_t = L_{t−4} × (1 + yoy_t) 精確鏈接。
    這個假設只影響序列最開頭，且誤差不會隨時間放大——
    若改用「缺去年同季就乘上個月」，每年同一季度會永久帶有乘數偏差，
    HP 缺口會被系統性扭曲（這是實作時最容易踩到的坑）。

    回傳 ([(period, level)], 無法鏈接的點數)。
    """
    yoy: Dict[int, float] = {}
    label: Dict[int, str] = {}
    for period, value in series:
        idx = _quarter_index(period)
        if idx is None or value is None:
            continue
        yoy[idx] = float(value)
        label[idx] = str(period)
    if not yoy:
        return [], 0

    keys = sorted(yoy)
    first = keys[0]
    g = (1.0 + yoy[first]) ** 0.25 - 1.0
    levels: Dict[int, float] = {}
    for k in range(4):
        idx = first + k
        if idx in yoy:
            levels[idx] = 100.0 * (1.0 + g) ** k

    missing = 0
    for idx in keys:
        if idx in levels:
            continue
        prev = levels.get(idx - 4)
        if prev is None:
            missing += 1
            continue
        levels[idx] = prev * (1.0 + yoy[idx])
    ordered = [(label[i], levels[i]) for i in keys if i in levels]
    return ordered, missing


def _apply_kkt(x: Sequence[float], lamb: float) -> List[float]:
    """計算 (I + λK′K)x，K 為 ground truth 的二階差分算子。"""
    n = len(x)
    out = [x[i] for i in range(n)]
    if n < 3:
        return out
    d = [x[i] - 2.0 * x[i + 1] + x[i + 2] for i in range(n - 2)]
    for j, dv in enumerate(d):
        out[j] += lamb * dv
        out[j + 1] += -2.0 * lamb * dv
        out[j + 2] += lamb * dv
    return out


def hp_filter(values: Sequence[float], lamb: float = DEFAULT_LAMBDA) -> List[float]:
    """回傳趨勢項 τ（與 values 等長）。共軛梯度法，對稱正定。"""
    y = [float(v) for v in values]
    n = len(y)
    if n < 3:
        return list(y)

    diag = [1.0 + lamb * (1.0 if i in (0, n - 1) else 5.0 if i in (1, n - 2) else 6.0)
            for i in range(n)]

    def dot(a: Sequence[float], b: Sequence[float]) -> float:
        return sum(ai * bi for ai, bi in zip(a, b))

    x = [0.0] * n
    r = list(y)                       # b − A·0
    z = [r[i] / diag[i] for i in range(n)]
    p = list(z)
    rz = dot(r, z)
    b_norm = math.sqrt(dot(y, y)) or 1.0
    max_iter = max(200, 20 * n)

    for _ in range(max_iter):
        ap = _apply_kkt(p, lamb)
        denom = dot(p, ap)
        if denom <= 0:
            break
        alpha = rz / denom
        for i in range(n):
            x[i] += alpha * p[i]
            r[i] -= alpha * ap[i]
        if math.sqrt(dot(r, r)) <= 1e-10 * b_norm:
            break
        z = [r[i] / diag[i] for i in range(n)]
        rz_new = dot(r, z)
        if rz == 0:
            break
        beta = rz_new / rz
        p = [z[i] + beta * p[i] for i in range(n)]
        rz = rz_new
    return x


@dataclass
class HpResult:
    """HP 濾波結果；序列不足時 available=False，而不是硬算一個假缺口。"""

    available: bool
    reason: str = ""
    gap: Optional[float] = None                 # 小數：-0.012 = -1.2%
    actual: Optional[float] = None
    potential: Optional[float] = None
    potential_growth: Optional[float] = None    # 潛在產出的近一年增速
    lamb: float = DEFAULT_LAMBDA
    n_obs: int = 0
    source: str = ""
    series: List[Tuple[str, float]] = field(default_factory=list)  # (期間, 缺口)

    @property
    def gap_pp(self) -> Optional[float]:
        return None if self.gap is None else self.gap * 100.0

    @property
    def label(self) -> str:
        if not self.available or self.gap is None:
            return "—"
        if self.gap > 0.005:
            return "高於潛在（產出正缺口）"
        if self.gap < -0.005:
            return "低於潛在（產出負缺口）"
        return "接近潛在水平"

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "gdp_gap": self.gap,
            "potential_growth": self.potential_growth,
            "lambda": self.lamb,
            "n_obs": self.n_obs,
            "label": self.label,
            "source": self.source,
        }


def seasonal_factors(values: Sequence[float], clip: float = 0.15) -> List[float]:
    """
    比率‑移動平均法的季度季節因子（中位數，抗異常值）。

    實質 GDP 指數是「未經季節調整」的水平和，Q1 通常明顯低於 Q4。
    直接對未調整序列做 HP 濾波，會把季節波動誤判成經濟週期，
    所以濾波前必須先除掉季節因子。
    """
    n = len(values)
    buckets: List[List[float]] = [[], [], [], []]
    for i in range(2, n - 2):
        ma = (0.5 * values[i - 2] + values[i - 1] + values[i]
              + values[i + 1] + 0.5 * values[i + 2]) / 4.0
        if ma > 0:
            buckets[i % 4].append(values[i] / ma)
    factors = []
    for arr in buckets:
        if arr:
            arr = sorted(arr)
            f = arr[len(arr) // 2]
        else:
            f = 1.0
        factors.append(min(1.0 + clip, max(1.0 - clip, f)))
    mean = sum(factors) / 4.0 or 1.0
    return [f / mean for f in factors]


def seasonal_adjust(values: Sequence[float], factors: Sequence[float]) -> List[float]:
    return [v / factors[i % 4] for i, v in enumerate(values)]


def build_gdp_gap_from_levels(
    series: Sequence[Tuple[str, float]],
    lamb: float = DEFAULT_LAMBDA,
    min_obs: int = 24,
    drop_head: int = 8,
    seasonal: bool = True,
    source: str = "",
) -> HpResult:
    """由實質 GDP 水平（指數）建立缺口；這是本引擎的首選路徑。"""
    points = []
    for period, level in series:
        idx = _quarter_index(period)
        if idx is None or level is None or level <= 0:
            continue
        points.append((idx, str(period), float(level)))
    points.sort()
    if len(points) < min_obs:
        return HpResult(
            available=False,
            reason=f"可用季度只有 {len(points)} 期，少於 {min_obs} 期，無法可靠濾波",
            lamb=lamb, n_obs=len(points), source=source,
        )

    periods = [p for _, p, _ in points]
    raw = [v for _, _, v in points]
    factors = seasonal_factors(raw) if seasonal else [1.0] * 4
    values = seasonal_adjust(raw, factors) if seasonal else raw

    if len(values) > drop_head + 12:
        periods = periods[drop_head:]
        values = values[drop_head:]

    trend = hp_filter(values, lamb)
    if not trend or trend[-1] == 0:
        return HpResult(available=False, reason="HP 濾波失敗", n_obs=len(values))

    gaps = [(periods[i], values[i] / trend[i] - 1.0) for i in range(len(values))]
    potential_growth = None
    if len(trend) >= 5 and trend[-5] > 0:
        potential_growth = trend[-1] / trend[-5] - 1.0

    note = f"{len(raw)} 季實質 GDP"
    if seasonal:
        note += f"（季節因子 {'/'.join(f'{f:.3f}' for f in factors)}）"
    note += f"；λ={lamb:g}"
    if source:
        note += f"；資料：{source}"

    return HpResult(
        available=True,
        gap=gaps[-1][1],
        actual=values[-1],
        potential=trend[-1],
        potential_growth=potential_growth,
        lamb=lamb,
        n_obs=len(values),
        source=note,
        series=gaps[-20:],
    )


def build_gdp_gap(
    series: Sequence[Tuple[str, float]],
    lamb: float = DEFAULT_LAMBDA,
    min_obs: int = 24,
    drop_head: int = 8,
    source: str = "",
) -> HpResult:
    """
    由季度「同比」建立缺口（備援路徑）。

    只有在拿不到官方實質 GDP 指數時才用；同比鏈接無法還原年內結構，
    即使做了季節調整，精度仍低於直接使用水平序列，因此會在 source 標明。
    """
    levels, approx = chain_yoy(series)
    result = build_gdp_gap_from_levels(
        levels, lamb=lamb, min_obs=min_obs, drop_head=drop_head,
        seasonal=True, source=(source + "（由同比鏈接，精度較低）").strip("；"))
    if result.available and approx:
        result.source += f"；{approx} 個缺季未能鏈接"
    return result
