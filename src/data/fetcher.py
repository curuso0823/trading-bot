"""
data/fetcher.py
資料抓取層：FinMind（歷史 + 籌碼）+ Fugle（即時報價）
所有外部 API 呼叫都在這裡，上層模組不直接碰 requests
"""
import os
import time
import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv
from src.utils.helpers import load_settings

load_dotenv()

# ---------- FinMind ----------

class FinMindFetcher:
    """
    FinMind 免費版注意事項：
    - 每日 API 請求上限：600 次（免費）
    - 批次掃描全市場時務必加 sleep
    - 資料為 T+1（法人資料當日無法取得）
    """

    BASE_URL = "https://api.finmindtrade.com/api/v4/data"

    def __init__(self):
        self.token = os.getenv("FINMIND_TOKEN")
        if not self.token:
            raise ValueError("FINMIND_TOKEN 未設定，請檢查 .env 檔案")
        settings = load_settings()
        self.sleep_sec = settings["data"]["finmind_sleep"]
        self.max_retry = settings["data"]["finmind_retry"]
        self.cache_days = settings["data"].get("cache_days", 1)
        self.cache_dir = Path(settings["data"].get("raw_data_path", "./data/raw")) / "finmind_cache"

    # ---------- 磁碟快取（免費額度 600 次/日，重複查詢一律走快取）----------

    def _cache_path(self, dataset: str, stock_id: str,
                    start_date: str, end_date: str) -> Path:
        return self.cache_dir / f"{dataset}__{stock_id}__{start_date}__{end_date}.pkl"

    def _cache_load(self, path: Path, end_date: str):
        """命中且有效回傳 DataFrame，否則 None。
        歷史資料（end_date < 今日）視為不可變、永久有效；
        含今日的查詢以 cache_days 當 TTL。"""
        if not path.exists():
            return None
        if end_date >= date.today().isoformat():
            if time.time() - path.stat().st_mtime > self.cache_days * 86400:
                return None
        try:
            return pd.read_pickle(path)
        except Exception:
            return None

    def _cache_save(self, path: Path, df: pd.DataFrame) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_pickle(path)
        except Exception as e:
            logger.warning(f"FinMind 快取寫入失敗 | {path.name} | {e}")

    def _request(self, dataset: str, stock_id: str,
                 start_date: str, end_date: str = None) -> pd.DataFrame:
        """通用請求，含磁碟快取、retry 與 rate-limit 保護"""
        import requests

        if end_date is None:
            end_date = date.today().isoformat()

        cache_path = self._cache_path(dataset, stock_id, start_date, end_date)
        cached = self._cache_load(cache_path, end_date)
        if cached is not None:
            return cached  # 快取命中：不打 API、不 sleep

        params = {
            "dataset": dataset,
            "data_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
            "token": self.token,
        }

        for attempt in range(self.max_retry):
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != 200:
                    logger.warning(f"FinMind status={data.get('status')} | {stock_id} | {dataset}")
                    return pd.DataFrame()
                df = pd.DataFrame(data["data"])
                time.sleep(self.sleep_sec)
                if not df.empty:
                    self._cache_save(cache_path, df)
                return df
            except Exception as e:
                logger.warning(f"FinMind retry {attempt+1}/{self.max_retry} | {e}")
                time.sleep(self.sleep_sec * (attempt + 1))

        logger.error(f"FinMind 請求失敗（已重試 {self.max_retry} 次）| {stock_id} | {dataset}")
        return pd.DataFrame()

    def get_daily_price(self, stock_id: str, start_date: str,
                        end_date: str = None, adjust: bool = True) -> pd.DataFrame:
        """
        取得日K資料。
        免費層用未還原 TaiwanStockPrice（TaiwanStockPriceAdj 為贊助者限定）；
        adjust=True 時以 TaiwanStockDividendResult 的除權息前後參考價做反向還原，
        使最新價維持實際成交價，等同還原股價（OHLC 全部還原）。
        回傳欄位：date, open, high, low, close, volume, adj_close
        註：adjust=True 會多一次 API 請求（除權息資料），全市場掃描可設 False 省額度。
        """
        df = self._request("TaiwanStockPrice", stock_id, start_date, end_date)
        if df.empty:
            return df

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # 標準化欄位名稱
        rename_map = {
            "open": "open", "max": "high", "min": "low",
            "close": "close", "Trading_Volume": "volume",
        }
        df = df.rename(columns=rename_map)
        # 過濾無效交易列：FinMind 對停牌/特殊狀況會回 0 價，會污染 MA/RSI 與回測停損判斷
        df = df[(df["close"] > 0) & (df["open"] > 0)].reset_index(drop=True)
        df["adj_close"] = df["close"]

        keep = ["date", "open", "high", "low", "close", "volume", "adj_close"]
        df = df[[c for c in keep if c in df.columns]]

        if adjust:
            div = self.get_dividend_result(stock_id, start_date, end_date)
            df = self._apply_back_adjust(df, div)

        return df

    def get_institutional(self, stock_id: str, start_date: str,
                          end_date: str = None) -> pd.DataFrame:
        """
        取得三大法人買賣超
        回傳欄位：date, stock_id, name, buy, sell, diff
        name 為英文：Foreign_Investor / Investment_Trust / Dealer_self / Dealer_Hedging / Foreign_Dealer_Self
        diff = buy - sell（單位：股），由本層計算（FinMind 原始資料無此欄）
        注意：T+1，今日資料明日才有
        """
        df = self._request("TaiwanStockInstitutionalInvestorsBuySell",
                            stock_id, start_date, end_date)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        # 此 dataset 僅有 buy/sell，無 diff；買賣超淨額 diff = buy - sell
        if {"buy", "sell"}.issubset(df.columns):
            df["diff"] = df["buy"].astype(float) - df["sell"].astype(float)
        return df.sort_values("date").reset_index(drop=True)

    def get_margin(self, stock_id: str, start_date: str,
                   end_date: str = None) -> pd.DataFrame:
        """
        取得融資融券資料
        回傳欄位：date, MarginPurchaseBuy, MarginPurchaseSell,
                  ShortSaleBuy, ShortSaleSell, MarginPurchaseLimit 等
        """
        df = self._request("TaiwanStockMarginPurchaseShortSale",
                            stock_id, start_date, end_date)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def get_dividend_result(self, stock_id: str, start_date: str,
                            end_date: str = None) -> pd.DataFrame:
        """
        除權息結果（含除權息前後參考價），用於還原股價。FinMind 免費層可用。
        回傳欄位：date(除權息交易日), before_price, after_price 等
        """
        df = self._request("TaiwanStockDividendResult", stock_id, start_date, end_date)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        for c in ["before_price", "after_price"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("date").reset_index(drop=True)

    @staticmethod
    def _apply_back_adjust(df: pd.DataFrame, div: pd.DataFrame) -> pd.DataFrame:
        """
        反向還原 OHLC，使最新價維持實際成交價（等同券商還原線圖）。涵蓋兩類公司行動：
        1) 除權息：用 TaiwanStockDividendResult 的 after/before 參考價比率。
        2) 分割/面額變更：除權息資料未涵蓋（如 0050 在 2025-06-18 之 1→4 分割），
           改由「單日收盤比值超出漲跌停可能範圍」偵測 —— 台股日限 ±10%，
           故比值 <0.70 或 >1.43 必為公司行動，且排除已知除權息日。
        """
        if df.empty:
            return df
        df = df.copy().sort_values("date").reset_index(drop=True)
        dts = df["date"].values

        events = []           # [(ex_date np.datetime64, ratio), ...]
        div_days = set()
        if not div.empty:
            valid = div[(div["before_price"] > 0) & (div["after_price"] > 0)]
            for _, r in valid.iterrows():
                d = pd.Timestamp(r["date"]).normalize()
                events.append((np.datetime64(d), float(r["after_price"]) / float(r["before_price"])))
                div_days.add(d)

        # 偵測分割（除權息資料未涵蓋）
        close = df["close"].values
        for i in range(1, len(close)):
            if close[i - 1] <= 0:
                continue
            rr = close[i] / close[i - 1]
            if np.isfinite(rr) and (rr < 0.70 or rr > 1.43):
                d = pd.Timestamp(dts[i]).normalize()
                if d not in div_days:
                    events.append((np.datetime64(d), float(rr)))

        if events:
            fac = np.ones(len(df), dtype=float)
            for ex, ratio in events:
                fac[dts < ex] *= ratio
            for col in ["open", "high", "low", "close"]:
                if col in df.columns:
                    df[col] = df[col] * fac
        df["adj_close"] = df["close"]
        return df


# ---------- Fugle ----------

class FugleFetcher:
    """
    Fugle MarketData（即時報價 + 歷史分K）
    免費版限制：每秒請求頻率有上限
    """

    def __init__(self):
        self.api_key = os.getenv("FUGLE_API_KEY")
        if not self.api_key:
            raise ValueError("FUGLE_API_KEY 未設定")

        # 延遲 import，避免套件未安裝時整個模組崩潰
        try:
            from fugle_marketdata import RestClient
            self.client = RestClient(api_key=self.api_key)
        except ImportError:
            logger.error("fugle-marketdata 未安裝：pip install fugle-marketdata")
            self.client = None

    def get_realtime_quote(self, stock_id: str, odd: bool = False) -> dict:
        """
        取得即時報價（Fugle 用純代號，非 .TW）。
        odd=True 取盤中零股報價（type=oddlot）。
        回傳含 lastPrice / bids / asks 等的 dict。
        """
        if not self.client:
            return {}
        try:
            kw = {"type": "oddlot"} if odd else {}
            return self.client.stock.intraday.quote(symbol=stock_id, **kw)
        except Exception as e:
            logger.error(f"Fugle 即時報價失敗 | {stock_id} | {e}")
            return {}

    def get_candles(self, stock_id: str, start_date: str,
                    end_date: str = None, timeframe: str = "D") -> pd.DataFrame:
        """
        取得歷史K線（D=日K，60=60分K）
        作為 FinMind 的備用資料源
        """
        if not self.client:
            return pd.DataFrame()
        try:
            if end_date is None:
                end_date = date.today().isoformat()
            data = self.client.stock.historical.candles(
                symbol=stock_id,
                from_=start_date,
                to=end_date,
                fields="open,high,low,close,volume",
            )
            df = pd.DataFrame(data.get("data", []))
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Fugle K線失敗 | {stock_id} | {e}")
            return pd.DataFrame()

    # ---------- 多標的並行（allocator：6 資產一次取數）----------

    def get_candles_multi(self, symbols, start_date: str, end_date: str = None,
                          timeframe: str = "D", max_workers: int = 6) -> dict[str, pd.DataFrame]:
        """
        並行取多標的歷史K線（ThreadPool），逐檔回 {symbol: DataFrame}。
        沿用既有 get_candles（同欄位/同排序/同 fallback 行為）；單檔失敗回該檔空 DataFrame、不影響其他檔。
        allocator 路徑用此一次抓 6 資產（MMF 為合成 NAV、不在此取數，由呼叫端排除）。
        max_workers 預設 6（對齊 data.scan_workers 平衡限流）。
        """
        from concurrent.futures import ThreadPoolExecutor

        syms = list(symbols)
        out: dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in syms}
        if not syms:
            return out
        if not self.client:
            return out

        def _one(sym: str) -> tuple[str, pd.DataFrame]:
            try:
                return sym, self.get_candles(sym, start_date, end_date, timeframe)
            except Exception as e:                       # get_candles 已內含 try；此為雙重保險
                logger.error(f"Fugle 多標的K線失敗 | {sym} | {e}")
                return sym, pd.DataFrame()

        workers = max(1, min(int(max_workers), len(syms)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for sym, df in ex.map(_one, syms):
                out[sym] = df
        return out

    def get_odd_quotes_multi(self, symbols, max_workers: int = 6) -> dict[str, dict]:
        """
        並行取多標的盤中零股報價（type=oddlot），逐檔回 {symbol: quote dict}。
        便利包裝：對每檔呼叫既有 get_realtime_quote(sym, odd=True)（簽名/行為不變）。
        allocator rebalance 時一次取 5 檔 ETF 的零股薄帳（餵 odd_lot_fill book-walk 成交）。
        """
        from concurrent.futures import ThreadPoolExecutor

        syms = list(symbols)
        out: dict[str, dict] = {s: {} for s in syms}
        if not syms or not self.client:
            return out

        def _one(sym: str) -> tuple[str, dict]:
            return sym, self.get_realtime_quote(sym, odd=True)

        workers = max(1, min(int(max_workers), len(syms)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for sym, q in ex.map(_one, syms):
                out[sym] = q
        return out


# ---------- T+1 完整收盤輔助（allocator regime / ref-price 用）----------

def completed_daily_closes(candles_by_sym: dict, today) -> dict:
    """從多標的日K（{sym: DataFrame}）取「今日未完成 bar 已剔除」的完整收盤 Series。

    T+1 紀律（對齊 sandbox regime `shift(1)`）：盤中（如 09:12）即時源可能回今日尚未收盤的
    in-progress bar；以此算 MA200/regime 會用到「未定價且早一日」的值 → 一律剔除「日期 ≥ today」
    的 bar，只保留完整交易日收盤。`compute_regime_on` 的契約即要求餵『截至昨日(含)收盤』序列。
    回 {sym: close Series(index=date)}；空/無 close 的檔 → 空 Series。
    """
    cut = pd.Timestamp(today)
    out: dict = {}
    for sym, df in (candles_by_sym or {}).items():
        if df is None or getattr(df, "empty", True) or "close" not in getattr(df, "columns", []):
            out[sym] = pd.Series(dtype=float)
        else:
            s = df.set_index("date")["close"].astype(float)
            out[sym] = s[s.index < cut]
    return out
