"""Kongre Takip: yerel web arayüzü.  python app.py  →  http://localhost:5060"""
import json
import os
from datetime import date, timedelta
from pathlib import Path

from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, request, send_from_directory

from kongre import db, returns, sync

app = Flask(__name__, static_folder="static", static_url_path="/static")
ROOT = Path(__file__).resolve().parent
STOCK_TYPES = ("ST", "OP", "PS", "EF")
DEFAULT_FAMOUS = ["Trump", "Vance", "Pelosi", "Gottheimer", "Crenshaw", "Taylor Greene", "Khanna", "McCaul",
                  "Jeffries", "Ocasio-Cortez", "Mike Johnson", "Moskowitz", "Bresnahan", "Luna"]


def _famous():
    """Ünlüler listesi: ayarlar.json → "unluler" (yoksa varsayılan liste). Ad parçası olarak eşleşir."""
    try:
        return json.loads((ROOT / "ayarlar.json").read_text()).get("unluler", DEFAULT_FAMOUS)
    except (OSError, ValueError):
        return DEFAULT_FAMOUS


def _famous_sql(col="c.member"):
    names = _famous() or ["-"]
    return "(" + " OR ".join(f"{col} LIKE ?" for _ in names) + ")", [f"%{n}%" for n in names]


def _is_famous(member, names):
    return any(n.lower() in (member or "").lower() for n in names)


def _since(days):
    return (date.today() - timedelta(days=int(days))).isoformat()


def _num_arg(name, default, lo, hi, kind=int):
    """Adres satırındaki sayı: boşsa varsayılan, sayı değilse 400, sınır dışındaysa sınıra çekilir."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return default
    try:
        v = kind(raw)
    except (ValueError, OverflowError):
        abort(400, f"{name} sayı olmalı")
    if v != v:   # NaN
        abort(400, f"{name} sayı olmalı")
    return max(lo, min(hi, v))


def _horizon():
    return _num_arg("horizon", None, 1, 3650)


# ---------------------------------------------------------------- yalnızca bu bilgisayardan erişim

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local(netloc):
    try:
        return urlsplit("//" + netloc).hostname in LOCAL_HOSTS
    except ValueError:
        return False


@app.before_request
def _only_local():
    """Uygulama yalnızca bu bilgisayardaki tarayıcı içindir.

    Host denetimi: başka bir alan adının bu sunucuya yönlendirilmesini (DNS rebinding) engeller.
    Origin denetimi: açık duran başka bir sitenin kullanıcı adına istek göndermesini (CSRF) engeller."""
    if not _is_local(request.host):
        abort(403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin is not None and not _is_local(urlsplit(origin).netloc):
            abort(403)
        if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            abort(403)


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.get("/")
def index():
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/api/status")
def api_status():
    n = db.query("SELECT COUNT(*) n, MAX(filed) last FROM congress_tx")[0]
    return jsonify({**sync.status, "n_tx": n["n"], "last_filed": n["last"]})


@app.get("/api/trades")
def api_trades():
    days = _num_arg("days", 30, 1, 3650)
    kind = request.args.get("type", "PS")          # PS: alım+satım, P, S, E (takas), all
    assets = request.args.get("assets", "stocks")  # stocks: hisse, ETF, opsiyon · all: tahvil vb. dahil
    party = request.args.get("party", "")
    min_value = _num_arg("min", 0, 0, 1e12, kind=float)
    q = request.args.get("q", "").strip()
    view = request.args.get("view", "list")

    where, args = ["c.filed>=?"], [_since(days)]
    if kind in ("P", "S", "E"):
        where.append("c.type=?"); args.append(kind)
    elif kind == "PS":
        where.append("c.type IN ('P','S')")
    if assets == "stocks":
        where.append(f"c.asset_type IN ({','.join('?' * len(STOCK_TYPES))})"); args += STOCK_TYPES
    if party in ("D", "R", "I"):
        where.append("c.party=?"); args.append(party)
    if min_value:
        where.append("c.amt_lo>=?"); args.append(min_value)
    if request.args.get("famous") == "1":
        f_sql, f_args = _famous_sql()
        where.append(f_sql); args += f_args
    if q:
        where.append("(c.member LIKE ? OR UPPER(c.ticker)=? OR c.asset LIKE ?)")
        args += [f"%{q}%", q.upper(), f"%{q}%"]
    w = " AND ".join(where)

    if view == "ticker":
        rows = db.query(f"""SELECT c.ticker, MAX(c.asset) asset,
                COUNT(DISTINCT CASE WHEN c.type='P' THEN c.member END) n_buyers,
                COUNT(DISTINCT CASE WHEN c.type='S' THEN c.member END) n_sellers,
                SUM(c.type='P') n_buys, SUM(c.type='S') n_sales,
                SUM(CASE WHEN c.type='P' THEN c.amt_lo ELSE 0 END) buy_lo,
                SUM(CASE WHEN c.type='S' THEN c.amt_lo ELSE 0 END) sale_lo,
                MAX(c.filed) last_filed, GROUP_CONCAT(DISTINCT c.member) members
            FROM congress_tx c WHERE {w} AND c.ticker IS NOT NULL
            GROUP BY UPPER(c.ticker) ORDER BY COUNT(DISTINCT c.member) DESC, n_buys + n_sales DESC LIMIT 300""", args)
    elif view == "member":
        rows = db.query(f"""SELECT c.member, c.party, c.state_dst, COUNT(*) n_tx,
                SUM(c.type='P') n_buys, SUM(c.type='S') n_sales,
                SUM(CASE WHEN c.type='P' THEN c.amt_lo ELSE 0 END) buy_lo,
                SUM(CASE WHEN c.type='S' THEN c.amt_lo ELSE 0 END) sale_lo,
                COUNT(DISTINCT c.doc_id) n_docs, MAX(c.filed) last_filed,
                GROUP_CONCAT(DISTINCT c.ticker) tickers
            FROM congress_tx c WHERE {w} GROUP BY c.member ORDER BY n_tx DESC LIMIT 300""", args)
        fam = _famous()
        for r in rows:
            r["famous"] = _is_famous(r["member"], fam)
    else:
        rows = db.query(f"""SELECT c.* FROM congress_tx c WHERE {w}
            ORDER BY c.filed DESC, c.doc_id DESC, c.tx_date DESC LIMIT 2000""", args)
        fam = _famous()
        for r in rows:
            r["famous"] = _is_famous(r["member"], fam)
        returns.attach(rows, horizon=_horizon())
    return jsonify(rows)


@app.get("/api/scorecard")
def api_scorecard():
    """"Piyasayı yendi mi?": hisse/ETF alım-satımlarının işlemden sonra S&P 500'e göre performansı."""
    days = _num_arg("days", 90, 1, 3650)
    where, args = "tx_date>=? AND asset_type IN ('ST','EF') AND type IN ('P','S') AND ticker IS NOT NULL", [_since(days)]
    if request.args.get("famous") == "1":
        f_sql, f_args = _famous_sql("member")
        where += " AND " + f_sql
        args += f_args
    rows = db.query(f"""SELECT member, party, state_dst, chamber, ticker, type, tx_date FROM congress_tx
                        WHERE {where}""", args)
    returns.attach(rows, horizon=_horizon())
    party = request.args.get("party", "")
    if party in ("D", "R", "I"):
        rows = [r for r in rows if r.get("party") == party]
    members, summary = returns.scorecard(rows, min_trades=_num_arg("min_trades", 3, 1, 10000))
    fam = _famous()
    for m in members:
        m["famous"] = _is_famous(m["member"], fam)
    priced = sum(1 for r in rows if r.get("excess") is not None)
    return jsonify({"members": members, "summary": summary, "n_rows": len(rows), "n_priced": priced})


@app.get("/api/reports")
def api_reports():
    days = _num_arg("days", 30, 1, 3650)
    return jsonify(db.query("SELECT * FROM congress_docs WHERE filed>=? ORDER BY filed DESC, id DESC LIMIT 1000",
                            (_since(days),)))


@app.post("/api/refresh")
def api_refresh():
    if not sync.status["running"]:
        import threading
        threading.Thread(target=sync.run, daemon=True).start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    db.init()
    if not os.environ.get("KONGRE_GUNCELLEME_YOK"):
        sync.start_background(int(os.environ.get("KONGRE_DAKIKA", 60)))
    port = int(os.environ.get("KONGRE_PORT", 5060))
    print(f"\n  Kongre Takip:  http://localhost:{port}\n  İlk güncelleme birkaç dakika sürer; sayfa veriler geldikçe dolar.\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
