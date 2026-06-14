"""探 Fugle 正確 quote API（round-lot vs odd-lot）+ 買賣價差。"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from fugle_marketdata import RestClient

c = RestClient(api_key=os.getenv("FUGLE_API_KEY"))


def show(label, **kw):
    try:
        q = c.stock.intraday.quote(symbol="2330", **kw)
        keys = list(q.keys())
        print(f"\n[{label}] keys: {keys}")
        for k in ["symbol", "lastPrice", "closePrice", "bids", "asks"]:
            if k in q:
                print(f"  {k}: {json.dumps(q[k], ensure_ascii=False)[:200]}")
    except Exception as e:
        print(f"\n[{label}] ERROR: {repr(e)[:200]}")


show("round-lot")
show("odd-lot type=oddlot", type="oddlot")
show("odd-lot type=ODDLOT", type="ODDLOT")
