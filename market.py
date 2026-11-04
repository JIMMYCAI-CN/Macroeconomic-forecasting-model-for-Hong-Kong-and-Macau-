"""
sources/market.py —— 港股市場與匯率輔助數據
=========================================================
本模組只抓「市場刻度」，不抓個股、不做選股：
  * 恒生指數水平與日收盤序列（Yahoo Finance chart JSON，免 key）
    → 用於計算已實現波動率，作為 VHSI 的代理值
  * HKD/CNY 即期匯率（Frankfurter／ECB 參考價）
    → 用於 PPP 錯配

恒指市盈率與股息率沒有穩定的免費即時介面，因此列為「可覆寫的市場估值輸入」：
預設值來自 EngineConfig.market，狀態標為「內建基準值」，
使用者可在 GUI／CLI 手動覆寫成券商或恒指公司公布的最新數字。
這比偷偷用一個看起來很精確的假數字誠實。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..models import Observation
from ..net import DataSourceError, fetch_json, now_stamp, read_cache, write_cache

YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/"
         "%5EHSI?range=1y&interval=1d")
FX_URL = "https://api.frankfurter.app/latest?from=HKD&to=CNY"
CACHE_HSI = "hsi_yahoo"
CACHE_FX = "fx_hkd_cny"
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "market_seed.json"


def _date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


# ------------------------------------------------------------------ HSI
def parse_yahoo(payload: Dict) -> Tuple[List[float], List[str]]:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise DataSourceError("Yahoo chart 回應沒有 result")
    item = result[0]
    stamps = item.get("timestamp") or []
    closes = ((item.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    values: List[float] = []
    dates: List[str] = []
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        values.append(float(close))
        dates.append(_date(float(ts)))
    if len(values) < 25:
        raise DataSourceError("恒指歷史少於 25 個交易日")
    return values, dates


def fetch_hsi(offline: bool = False) -> Tuple[Optional[Observation], List[float]]:
    cached = read_cache(CACHE_HSI) or {}
    if not offline:
        try:
            values, dates = parse_yahoo(fetch_json(YAHOO))
            write_cache(CACHE_HSI, {"closes": values[-260:], "dates": dates[-260:]})
            return Observation(
                key="hsi", label="恒生指數", value=values[-1], period=dates[-1],
                source="Yahoo Finance（恒指日收盤）", url=YAHOO, status="live",
            ), values[-260:]
        except Exception:  # noqa: BLE001 - 降級到快取
            pass

    closes = [float(x) for x in cached.get("closes", [])]
    dates = list(cached.get("dates", []))
    if closes:
        return Observation(
            key="hsi", label="恒生指數", value=closes[-1],
            period=dates[-1] if dates else "",
            source=f"恒指本地快取（{cached.get('fetched_at', '時間未知')}）",
            url=YAHOO, status="cache",
            fetched_at=str(cached.get("fetched_at", "")),
        ), closes

    seed = _seed_market()
    if "hsi_level" in seed:
        item = seed["hsi_level"]
        return Observation(
            key="hsi", label="恒生指數", value=float(item["value"]),
            period=str(item.get("period", "")),
            source="恒指內建基準值（離線備用）", status="seed",
            note=str(item.get("note", "")),
        ), []
    return None, []


# ------------------------------------------------------------------ FX
def fetch_fx(offline: bool = False) -> Optional[Observation]:
    cached = read_cache(CACHE_FX) or {}
    if not offline:
        try:
            payload = fetch_json(FX_URL)
            rate = float((payload.get("rates") or {}).get("CNY"))
            date = str(payload.get("date", ""))
            write_cache(CACHE_FX, {"value": rate, "date": date})
            return Observation(
                key="fx", label="HKD/CNY 即期", value=rate, period=date,
                source="Frankfurter（ECB 參考匯率）", url=FX_URL, status="live",
            )
        except Exception:  # noqa: BLE001
            pass
    if cached.get("value"):
        return Observation(
            key="fx", label="HKD/CNY 即期", value=float(cached["value"]),
            period=str(cached.get("date", "")),
            source=f"匯率本地快取（{cached.get('fetched_at', '時間未知')}）",
            url=FX_URL, status="cache",
            fetched_at=str(cached.get("fetched_at", "")),
        )
    seed = _seed_market()
    if "hkd_cny" in seed:
        item = seed["hkd_cny"]
        return Observation(
            key="fx", label="HKD/CNY 即期", value=float(item["value"]),
            period=str(item.get("period", "")),
            source="匯率內建基準值（離線備用）", status="seed",
        )
    return None


# ------------------------------------------------------------------ 估值
def _seed_market() -> Dict[str, Dict[str, object]]:
    try:
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def valuation_observations(cfg) -> Tuple[Observation, Observation]:
    """恒指 PE／股息率：有種子檔就用種子，否則用 config 預設，皆標示為內建。"""
    seed = _seed_market()
    pe = seed.get("hsi_pe") or {}
    dy = seed.get("hsi_div_yield") or {}
    pe_val = float(pe.get("value", cfg.hsi_pe))
    dy_val = float(dy.get("value", cfg.hsi_div_yield))
    pe_obs = Observation(
        key="hsi_pe", label="恒指市盈率", value=pe_val,
        period=str(pe.get("period", "")),
        source="市場估值內建基準（可手動覆寫）",
        status="seed", note="建議覆寫為恒生指數公司或券商公布的最新數值",
    )
    dy_obs = Observation(
        key="hsi_dy", label="恒指股息率", value=dy_val,
        period=str(dy.get("period", "")),
        source="市場估值內建基準（可手動覆寫）",
        status="seed",
    )
    return pe_obs, dy_obs


def fetch_all(offline: bool = False, market_cfg=None) -> Dict[str, object]:
    """回傳市場原始輸入字典（MarketInputs 的建構留給 engine，避免循環匯入）。"""
    hsi, closes = fetch_hsi(offline=offline)
    fx = fetch_fx(offline=offline)
    pe, dy = valuation_observations(market_cfg)
    return {
        "hsi_level": hsi,
        "hsi_pe": pe,
        "hsi_div_yield": dy,
        "vhsi": None,            # 由 engine 以已實現波動率補上（標示代理）
        "hkd_cny": fx,
        "closes": closes,
    }
