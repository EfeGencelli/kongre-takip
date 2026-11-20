"""Getiri katmanı: "işlemden bu yana hisse ne yaptı, aynı dönemde S&P 500 ne yaptı?"

Günlük kapanışlar Yahoo'dan (2 yıl) çekilir ve hisse başına tek satır olarak `price_hist` tablosunda tutulur.
Raporlarda işlem fiyatı bildirilmediği için işlem günündeki kapanış kullanılır; kıyas için S&P 500'ün (SPY)
aynı tarihteki kapanışı alınır.

Satışlarda "doğru zamanlama", satıştan sonra hissenin S&P'nin gerisinde kalmasıdır; skor hesaplarında
alımların farkı (+), satışların farkı (−) işaretiyle sayılır.
"""
import bisect
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

from . import db

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def yahoo_symbol(t):
    return t.upper().replace(".", "-").replace("/", "-")   # BRK.B → BRK-B

BENCH = "SPY"
REFRESH_SECONDS = 12 * 3600
_cache = {}   # ticker -> (yüklenme zamanı, tarihler, kapanışlar)


def _fetch(ticker):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol(ticker)}",
                     params={"range": "2y", "interval": "1d"}, timeout=20, headers=UA)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    stamps = res.get("timestamp") or []
    q = res["indicators"]["quote"][0].get("close") or []
    adj = ((res["indicators"].get("adjclose") or [{}])[0].get("adjclose")) or q   # bölünme ve temettü düzeltmeli
    dates, closes = [], []
    for ts, c in zip(stamps, adj):
        if c is None:
            continue
        d = date.fromtimestamp(ts).isoformat()
        if dates and dates[-1] == d:
            closes[-1] = c
        else:
            dates.append(d)
            closes.append(round(c, 4))
    return dates, closes


def _valid(t):
    return bool(t) and len(t) <= 7 and "$" not in t and t.replace(".", "").replace("-", "").isalnum()


def tickers_needed():
    """Son ~2 yılın Kongre ve Başkan hisse/ETF işlemleri + kıyas endeksi."""
    rows = db.query("""SELECT DISTINCT UPPER(ticker) t FROM congress_tx WHERE ticker IS NOT NULL
                       AND asset_type IN ('ST','OP','EF') AND tx_date>=date('now','-700 day')""")
    return sorted({BENCH} | {r["t"] for r in rows if _valid(r["t"])})


def sync(stop=None, limit=4000, extra=()):
    """Kapanışları 12 saatten eski olanları yeniler. Dönen: (yenilenen, toplam istenen).
    `extra`: başka modüllerin istediği semboller (ör. 13F fon hareketleri)."""
    want = sorted(set(tickers_needed()) | {t.upper() for t in extra if _valid((t or "").upper())})
    fresh = {r["ticker"] for r in db.query("SELECT ticker FROM price_hist WHERE updated>=?",
                                           (time.time() - REFRESH_SECONDS,))}
    todo = [t for t in want if t not in fresh][:limit]

    def one(t):
        if stop and stop.is_set():
            return None
        try:
            d, c = _fetch(t)
            return (t, json.dumps(d), json.dumps(c), time.time()) if d else (t, "[]", "[]", time.time())
        except requests.HTTPError as e:   # bilinmeyen / borsadan çıkmış sembol: 12 saat sonra yeniden dene
            code = e.response.status_code if e.response is not None else 0
            return (t, "[]", "[]", time.time()) if code in (400, 404, 422) else None
        except Exception:
            return None

    with ThreadPoolExecutor(6) as ex:
        rows = [r for r in ex.map(one, todo) if r]
    db.executemany("INSERT OR REPLACE INTO price_hist(ticker, dates, closes, updated) VALUES(?,?,?,?)", rows)
    _cache.clear()
    return len(rows), len(want)


# ---------------------------------------------------------------- hesap

def _series(ticker):
    t = (ticker or "").upper()
    hit = _cache.get(t)
    if hit and time.time() - hit[0] < 600:
        return hit[1], hit[2]
    r = db.query("SELECT dates, closes FROM price_hist WHERE ticker=?", (t,))
    d, c = (json.loads(r[0]["dates"]), json.loads(r[0]["closes"])) if r else ([], [])
    _cache[t] = (time.time(), d, c)
    return d, c


def preload(tickers):
    """Bir istekte çok satır hesaplanacaksa serileri tek sorguda yükler."""
    need = [t.upper() for t in set(tickers) if t and t.upper() not in _cache]
    for i in range(0, len(need), 500):
        part = need[i:i + 500]
        for r in db.query(f"SELECT ticker, dates, closes FROM price_hist WHERE ticker IN ({','.join('?' * len(part))})",
                          part):
            _cache[r["ticker"]] = (time.time(), json.loads(r["dates"]), json.loads(r["closes"]))


def close_on(ticker, day):
    """`day` günü ya da öncesindeki son kapanış (hafta sonu/tatil için)."""
    d, c = _series(ticker)
    i = bisect.bisect_right(d, day) - 1
    if i < 0 or (date.fromisoformat(day) - date.fromisoformat(d[i])).days > 6:
        return None
    return c[i]


def last_close(ticker):
    d, c = _series(ticker)
    return (d[-1], c[-1]) if d else (None, None)


def _end_day(start, horizon):
    if not horizon:
        return None
    return (date.fromisoformat(start) + timedelta(days=int(horizon))).isoformat()


def perf(ticker, start, horizon=None, start_price=None):
    """İşlem gününden bugüne (ya da `horizon` gün sonrasına) hisse ve SPY getirisi (%).

    Dönen: {"ret", "spy", "excess", "days"} ya da None (veri yoksa / süre dolmadıysa)."""
    if not ticker or not start:
        return None
    start = start[:10]   # bazı Form 4 tarihleri saat dilimiyle gelir: 2026-11-19-05:00
    p0 = start_price or close_on(ticker, start)
    s0 = close_on(BENCH, start)
    if not p0 or not s0:
        return None
    end = _end_day(start, horizon)
    if end:
        if end > date.today().isoformat():
            return None   # süre henüz dolmadı
        p1, s1 = close_on(ticker, end), close_on(BENCH, end)
        days = int(horizon)
    else:
        last, p1 = last_close(ticker)
        s1 = last_close(BENCH)[1]
        days = (date.fromisoformat(last) - date.fromisoformat(start)).days if last else None
    if not p1 or not s1:
        return None
    ret = (p1 / p0 - 1) * 100
    spy = (s1 / s0 - 1) * 100
    return {"ret": round(ret, 2), "spy": round(spy, 2), "excess": round(ret - spy, 2), "days": days}


def attach(rows, ticker_key="ticker", date_key="tx_date", price_key=None, horizon=None, suffix=""):
    """Satırlara ret / spy_ret / excess alanlarını (sonlarına `suffix` eklenerek) yerinde ekler."""
    preload([BENCH] + [r.get(ticker_key) or "" for r in rows])
    for r in rows:
        p = perf(r.get(ticker_key), r.get(date_key), horizon,
                 start_price=r.get(price_key) if price_key else None)
        r["ret" + suffix], r["spy_ret" + suffix], r["excess" + suffix] = \
            (p["ret"], p["spy"], p["excess"]) if p else (None, None, None)
    return rows



def scorecard(rows, min_trades=3):
    """Kongre işlemleri (getiri eklenmiş) → üye bazında karne ve genel özet.

    Alım: fark = hisse − S&P. Satış: fark = S&P − hisse (satıştan sonra düşen hisse iyi zamanlamadır)."""
    members, groups = {}, {"Hepsi": [], "D": [], "R": [], "W": []}
    for r in rows:
        if r.get("excess") is None or r["type"] not in ("P", "S"):
            continue
        edge = r["excess"] if r["type"] == "P" else -r["excess"]
        m = members.setdefault(r["member"], {"member": r["member"], "party": r.get("party"),
                                             "state_dst": r.get("state_dst"), "chamber": r.get("chamber"),
                                             "buys": [], "sales": []})
        (m["buys"] if r["type"] == "P" else m["sales"]).append((r["ret"], r["spy_ret"], edge))
        if r["type"] == "P" and r.get("chamber") == "W":   # Beyaz Saray ayrı grupta: binlerce işlemi Kongre ortalamasını ezmesin
            groups["W"].append((r["ret"], r["spy_ret"], edge))
        elif r["type"] == "P":
            groups["Hepsi"].append((r["ret"], r["spy_ret"], edge))
            if r.get("party") in groups:
                groups[r["party"]].append((r["ret"], r["spy_ret"], edge))

    def avg(xs, i):
        return round(sum(x[i] for x in xs) / len(xs), 2) if xs else None

    def hit(xs):
        return round(sum(1 for x in xs if x[2] > 0) / len(xs) * 100) if xs else None

    out = []
    for m in members.values():
        b, s = m.pop("buys"), m.pop("sales")
        if len(b) + len(s) < min_trades:
            continue
        both = b + s
        m.update({"n_buys": len(b), "n_sales": len(s),
                  "buy_ret": avg(b, 0), "buy_spy": avg(b, 1), "buy_edge": avg(b, 2), "buy_hit": hit(b),
                  "sale_edge": avg(s, 2), "sale_hit": hit(s),
                  "edge": avg(both, 2), "hit": hit(both)})
        out.append(m)
    out.sort(key=lambda m: m["edge"], reverse=True)
    summary = [{"group": g, "n": len(xs), "ret": avg(xs, 0), "spy": avg(xs, 1), "edge": avg(xs, 2), "hit": hit(xs)}
               for g, xs in groups.items()]
    return out, summary
