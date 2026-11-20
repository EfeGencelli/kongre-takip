"""SEC'in şirket listesi (company_tickers.json): Başkan raporlarındaki şirket adlarını sembole çevirmek için.

SEC, otomatik isteklerde iletişim bilgisi içeren bir User-Agent ister: KONGRE_SEC_UA ortam değişkenine
"Adınız eposta@ornek.com" biçiminde yazın. Yoksa genel bir değer kullanılır (SEC reddedebilir).
"""
import json
import os
import time

import requests

from . import db

URL = "https://www.sec.gov/files/company_tickers.json"
_tickers = {}


def load():
    path = db.DATA_DIR / "company_tickers.json"
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        ua = os.environ.get("KONGRE_SEC_UA", "kongre-takip acik-kaynak")
        try:
            r = requests.get(URL, headers={"User-Agent": ua}, timeout=60)
            r.raise_for_status()
            path.write_bytes(r.content)
        except Exception:
            if not path.exists():
                return   # liste yoksa yalnızca Yahoo araması kullanılır
    raw = json.loads(path.read_text())
    by_cik, by_ticker = {}, {}
    for k, v in raw.items():
        rank = int(k) + 1   # liste kabaca piyasa değerine göre sıralı
        cik = int(v["cik_str"])
        by_cik.setdefault(cik, {"ticker": v["ticker"], "name": v["title"], "rank": rank})
        by_ticker[v["ticker"].upper()] = {"cik": cik, "name": v["title"], "rank": rank}
    _tickers["by_cik"], _tickers["by_ticker"] = by_cik, by_ticker


def ticker_info(ticker):
    if not _tickers:
        load()
    return (_tickers.get("by_ticker") or {}).get((ticker or "").upper())
