"""
sources/hkma.py —— 香港金管局：10 年期港元政府債券收益率
=========================================================
規則要求「香港 rf = HKMA 10 年期港元政府債券收益率」。
實務上有兩條官方路徑，本模組依序嘗試：

  1. HKMA 公開 API（JSON，最即時）
     /public/market-data-and-statistics/monthly-statistical-bulletin/
      ibpgsbp/instit-bond-price-yield-daily-ibpgsbp-hkd
      → 取 closing_ref_rate_10y（收市參考價），沒有才退回 ind_pricing_10y

  2. HKMA 月報表 10.4.5 的官方 XLS（T10040301.xls）
     API 被 WAF 攔截或改版時，直接讀這份每日收益率表。
     需要可選依賴 xlrd（只支援 .xls）。

  3. 本地快取 → 4. 內建基準值（data/hk_rf_seed.json）
     兩者都會標記狀態，報告會寫明「不是即時數據」。

注意：香港政府債券計劃（GBP）2024 年起逐步由基建債券計劃（IBP）及
政府可持續債券計劃（GSBP）接棒，基準年期曲線改由 IBP／GSBP 提供，
所以這裡抓的是 10.4.5 而不是舊的 9.4.3（舊表 2025 年 1 月後已無報價）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models import Observation
from ..net import (
    CACHE_DIR,
    DataSourceError,
    download,
    fetch_json,
    read_cache,
    write_cache,
)

API_URL = (
    "https://api.hkma.gov.hk/public/market-data-and-statistics/"
    "monthly-statistical-bulletin/ibpgsbp/"
    "instit-bond-price-yield-daily-ibpgsbp-hkd"
)
XLS_URL = (
    "https://www.hkma.gov.hk/media/eng/doc/market-data-and-statistics/"
    "monthly-statistical-bulletin/T10040301.xls"
)
SOURCE_NAME = "香港金管局 HKMA"
CACHE_KEY = "hkma_10y"
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "hk_rf_seed.json"


# ------------------------------------------------------------------ 工具
def _num(value: Any) -> Optional[float]:
    if value in (None, "", "-", "N/A"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _percent(value: float) -> float:
    """HKMA 的收益率以「百分點」表示（4.022 代表 4.022%）。"""
    return value / 100.0


# ------------------------------------------------------------------ 1. API
def parse_api(payload: Dict[str, Any]) -> Tuple[float, str]:
    """從 API JSON 取出最新一筆 10 年期收益率，回傳 (小數值, 日期)。"""
    if not payload.get("header", {}).get("success", False):
        raise DataSourceError("HKMA API 回應失敗：" + str(payload.get("header")))
    records: List[Dict[str, Any]] = payload.get("result", {}).get("records") or []
    best: Optional[Tuple[str, float]] = None
    for row in records:
        date = str(row.get("end_of_date") or "")
        value = _num(row.get("closing_ref_rate_10y"))
        if value is None:
            value = _num(row.get("ind_pricing_10y"))
        if value is None or not date:
            continue
        if best is None or date > best[0]:
            best = (date, value)
    if best is None:
        raise DataSourceError("HKMA API 沒有可用的 10 年期收益率")
    return _percent(best[1]), best[0]


def fetch_via_api() -> Observation:
    value, date = parse_api(fetch_json(API_URL))
    write_cache(CACHE_KEY, {"value": value, "date": date, "url": API_URL, "method": "api"})
    return Observation(
        key="rf",
        label="10 年期港元政府債收益率",
        value=value,
        period=date,
        source="HKMA IBP／GSBP 每日基準收益率（API）",
        url=API_URL,
        status="live",
    )


# ------------------------------------------------------------------ 2. XLS
def parse_xls_table(rows: Sequence[Sequence[Any]], datemode: int = 0) -> Tuple[float, str]:
    """
    解析 10.4.5 每日收益率表的二維陣列。

    表格長相（節錄）：
        row 15: ... ['3-year','5-year','7-year','10-year','15-year','20-year',
                     '', '3-year','5-year','7-year','10-year','15-year','20-year']
        row 11: ... ['Indicative Reference Pricings', ..., 'Closing Reference Pricings']
        row 20+: [ '', '', 45588, 2.951, '-', ..., 2.963, ... ]
                 日期在第 3 欄，右半部是收市參考價

    這裡不硬編欄號，而是先找表頭再定位，避免 HKMA 改版就整個炸掉。
    """
    import datetime

    def text(cell: Any) -> str:
        return str(cell).strip() if cell is not None else ""

    # 找表頭列：同時出現兩個 '10-year' 的那一列
    header_idx = -1
    for i, row in enumerate(rows):
        if sum(1 for c in row if text(c).startswith("10-year")) >= 1 and any(
            text(c).startswith("3-year") for c in row
        ):
            header_idx = i
            break
    if header_idx < 0:
        raise DataSourceError("XLS 找不到收益率表頭")

    header = [text(c) for c in rows[header_idx]]
    ten_cols = [i for i, c in enumerate(header) if c.startswith("10-year")]
    if not ten_cols:
        raise DataSourceError("XLS 缺少 10 年期欄位")

    # 判斷哪一組是「收市參考價」：看上方兩列的群組標題
    closing_col = ten_cols[-1]
    for probe in (header_idx - 1, header_idx - 2, header_idx - 3, header_idx - 4):
        if probe < 0:
            continue
        group_row = [text(c) for c in rows[probe]]
        starts = [i for i, c in enumerate(group_row) if c]
        if any("Closing" in c for c in group_row):
            closing_start = min(i for i, c in enumerate(group_row) if "Closing" in c)
            # 取該群組內「10-year」對應的欄
            for col in ten_cols:
                if col >= closing_start:
                    closing_col = col
                    break
            break
        _ = starts

    # 日期欄：資料列中出現 Excel 序號（>40000）的那一欄
    date_col = -1
    for row in rows[header_idx + 1 : header_idx + 40]:
        for i, cell in enumerate(row):
            if isinstance(cell, (int, float)) and 40000 < float(cell) < 60000:
                date_col = i
                break
        if date_col >= 0:
            break
    if date_col < 0:
        raise DataSourceError("XLS 找不到日期欄")

    latest: Optional[Tuple[float, float]] = None  # (serial date, value)
    for row in rows[header_idx + 1 :]:
        if date_col >= len(row):
            continue
        serial = row[date_col]
        if not isinstance(serial, (int, float)) or not (40000 < float(serial) < 60000):
            continue
        value = _num(row[closing_col]) if closing_col < len(row) else None
        if value is None:
            continue
        if latest is None or float(serial) > latest[0]:
            latest = (float(serial), value)
    if latest is None:
        raise DataSourceError("XLS 沒有可用的 10 年期收益率")

    date = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(latest[0]))
    return _percent(latest[1]), date.isoformat()


def fetch_via_xls() -> Observation:
    try:
        import xlrd  # 可選依賴；沒裝就跳過這條路徑
    except ImportError as exc:  # pragma: no cover - 取決於環境
        raise DataSourceError("未安裝 xlrd，無法解析官方 XLS") from exc

    dest = CACHE_DIR / "T10040301.xls"
    download(XLS_URL, dest, timeout=90)
    book = xlrd.open_workbook(str(dest), on_demand=True)
    sheet = book.sheet_by_index(0)
    rows = [sheet.row_values(r) for r in range(sheet.nrows)]
    value, date = parse_xls_table(rows, book.datemode)
    write_cache(CACHE_KEY, {"value": value, "date": date, "url": XLS_URL, "method": "xls"})
    return Observation(
        key="rf",
        label="10 年期港元政府債收益率",
        value=value,
        period=date,
        source="HKMA 月報表 10.4.5（官方 XLS）",
        url=XLS_URL,
        status="file",
    )


# ------------------------------------------------------------------ 3/4. 快取與種子
def _from_cache() -> Observation:
    data = read_cache(CACHE_KEY)
    if not data or not data.get("value"):
        raise DataSourceError("沒有可用的本地快取")
    return Observation(
        key="rf",
        label="10 年期港元政府債收益率",
        value=float(data["value"]),
        period=str(data.get("date") or "unknown"),
        source=f"HKMA 本地快取（{data.get('fetched_at', '時間未知')}）",
        url=str(data.get("url", "")),
        status="cache",
        fetched_at=str(data.get("fetched_at", "")),
    )


def _from_seed() -> Observation:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return Observation(
        key="rf",
        label="10 年期港元政府債收益率",
        value=float(data["value"]),
        period=str(data["as_of"]),
        source="HKMA 內建基準值（離線備用）",
        url=str(data.get("url", "")),
        status="seed",
        note=str(data.get("note", "")),
    )


# ------------------------------------------------------------------ 對外
def fetch_rf(offline: bool = False) -> Observation:
    """依序嘗試 API → XLS → 快取 → 種子值。"""
    errors: List[str] = []
    if not offline:
        for name, func in (("API", fetch_via_api), ("XLS", fetch_via_xls)):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 - 任何失敗都降級
                errors.append(f"{name}: {exc}")
    try:
        return _from_cache()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cache: {exc}")
    obs = _from_seed()
    obs.note = "；".join(filter(None, [obs.note, "所有即時來源不可用"]))
    return obs
