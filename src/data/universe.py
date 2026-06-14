"""
data/universe.py
台股股票池管理：維護上市+上櫃可交易清單
"""
import pandas as pd
import requests
from io import StringIO
from pathlib import Path
from loguru import logger
from src.utils.helpers import tw_stock_list_path


def fetch_tw_stock_universe(force_refresh: bool = False) -> pd.DataFrame:
    """
    取得台股上市+上櫃股票清單
    本地快取，不需每次重抓

    回傳 DataFrame 欄位：stock_id, name, market(TWSE/OTC), industry
    """
    cache_path = tw_stock_list_path()

    if cache_path.exists() and not force_refresh:
        df = pd.read_csv(cache_path, dtype={"stock_id": str})
        logger.info(f"股票池從快取載入：{len(df)} 檔")
        return df

    logger.info("抓取台股股票池...")
    dfs = []

    # 上市（TWSE）
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        resp = requests.get(url, timeout=15)
        resp.encoding = "big5"
        tables = pd.read_html(StringIO(resp.text))
        df_twse = tables[0].copy()
        # 解析格式：股票代號 股票名稱
        df_twse.columns = df_twse.iloc[0]
        df_twse = df_twse[1:]
        df_twse = df_twse[["有價證券代號及名稱", "市場別", "產業別"]].copy()
        df_twse[["stock_id", "name"]] = df_twse["有價證券代號及名稱"].str.split(
            r"\s+", n=1, expand=True
        )
        df_twse["market"] = "TWSE"
        df_twse["industry"] = df_twse["產業別"]
        dfs.append(df_twse[["stock_id", "name", "market", "industry"]])
    except Exception as e:
        logger.error(f"抓取上市清單失敗：{e}")

    # 上櫃（OTC）
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
        resp = requests.get(url, timeout=15)
        resp.encoding = "big5"
        tables = pd.read_html(StringIO(resp.text))
        df_otc = tables[0].copy()
        df_otc.columns = df_otc.iloc[0]
        df_otc = df_otc[1:]
        df_otc = df_otc[["有價證券代號及名稱", "市場別", "產業別"]].copy()
        df_otc[["stock_id", "name"]] = df_otc["有價證券代號及名稱"].str.split(
            r"\s+", n=1, expand=True
        )
        df_otc["market"] = "OTC"
        df_otc["industry"] = df_otc["產業別"]
        dfs.append(df_otc[["stock_id", "name", "market", "industry"]])
    except Exception as e:
        logger.error(f"抓取上櫃清單失敗：{e}")

    if not dfs:
        logger.error("股票池抓取完全失敗")
        return pd.DataFrame()

    df_all = pd.concat(dfs, ignore_index=True)

    # 過濾：只保留 4 碼純數字的普通股（排除 ETF、權證、特別股）
    df_all = df_all[
        df_all["stock_id"].str.match(r"^\d{4}$")
    ].dropna(subset=["stock_id"]).reset_index(drop=True)

    # 快取到本地
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_csv(cache_path, index=False)
    logger.info(f"股票池已更新：{len(df_all)} 檔，儲存至 {cache_path}")

    return df_all


def get_stock_ids(market: str = "all") -> list[str]:
    """
    取得股票代號清單
    market: 'all' / 'TWSE' / 'OTC'
    """
    df = fetch_tw_stock_universe()
    if market != "all":
        df = df[df["market"] == market]
    return df["stock_id"].tolist()
