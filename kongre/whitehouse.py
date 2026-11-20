"""Beyaz Saray: Başkanın hisse işlemleri (OGE Form 278-T periyodik işlem raporları).

Kaynak: ABD Hükümet Etiği Ofisi'nin Başkan / Başkan Yardımcısı dizini. Raporlar taranmış PDF'tir ve içlerindeki
metin katmanı çok hatalıdır; bu yüzden sayfalar macOS Vision ile yeniden okunur (`bin/kongre-ocr`, ocr/ocr.swift).
Satırlar sütun konumlarından kurulur: açıklama / tür / tarih / (30 günü geçti mi) tutar.

Raporlarda sembol yoktur; varlık adı Yahoo aramasıyla sembole çevrilir (`name_map` tablosunda saklanır).
Kayıtlar Kongre işlemleriyle aynı tabloya (`congress_tx`, chamber='W') yazılır; böylece liste, karne ve getiri
hesapları aynen çalışır.
"""
import hashlib
import json
import math
import re
import subprocess
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from . import db
from . import seclist as sec

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
BASE = "https://extapps2.oge.gov"
INDEX = BASE + "/201/Presiden.nsf/President%20and%20Vice%20President%20Index?OpenView"
OCR_BIN = Path(__file__).resolve().parent.parent / "bin" / "kongre-ocr"

# dizindeki ad → uygulamada görünen ad, parti, unvan
PEOPLE = {"Trump": ("Donald J. Trump", "R", "Başkan"), "Vance": ("JD Vance", "R", "Başkan Yrd.")}

# OGE tutar aralıklarının alt sınırları → üst sınır
BRACKETS = [(1001, 15000), (15001, 50000), (50001, 100000), (100001, 250000), (250001, 500000),
            (500001, 1000000), (1000001, 5000000), (5000001, 25000000), (25000001, 50000000), (50000001, None)]


# ---------------------------------------------------------------- dizin

def list_reports():
    """Dizindeki 278-T raporları: [{"person", "filed", "url"}]."""
    t = requests.get(INDEX, headers=UA, timeout=60).text
    out, person = [], None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        name = re.search(r"Collapse=\d+#\d+[^>]*>(?:<[^>]+>)*\s*([^<,]+),", row)
        if name:
            person = name.group(1).strip()
            continue
        link = re.search(r"href='([^']+\$FILE/[^']+)'>(?:<img[^>]*>)?\s*278 Transaction \((\d{2}/\d{2}/\d{4})\)", row)
        if link and person in PEOPLE:
            url = BASE + urllib.parse.quote(link.group(1), safe="/$+,.()-_")
            filed = datetime.strptime(link.group(2), "%m/%d/%Y").date().isoformat()
            out.append({"person": person, "filed": filed, "url": url})
    return out


# ---------------------------------------------------------------- OCR ve satırlar

def ocr(pdf_path):
    res = subprocess.run([str(OCR_BIN), str(pdf_path)], capture_output=True, timeout=1800)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode(errors="replace")[:200] or "OCR başarısız")
    return [json.loads(l) for l in res.stdout.decode().splitlines() if l.strip()]


TYPE_WORD = re.compile(r"(?i)(?<![A-Za-z])(?:[lI|]?\s?[pdo]?u?rch\w*|purc\w*|sa[l1i][eoc]|exchange\w*)(?![A-Za-z])"
                       r"(?:\s*\(partial\))?")
DATE_TOKEN = re.compile(r"^[0-9Il|]{1,2}[/lI|1][0-9Il|]{1,2}[/lI|][0-9Il|]{2,4}$")
DESC_HDR = re.compile(r"^D[eo]scr")
TYPE_HDR, DATE_HDR, AMT_HDR = re.compile(r"^Typ"), re.compile(r"^Dat[eo]$"), re.compile(r"^Amount")


def _digits(s):
    return s.replace("I", "1").replace("l", "1").replace("|", "1").replace("O", "0").replace("o", "0")


def parse_date(tok, filed):
    """OCR tarihini düzeltir; işlem tarihi bildirimden önce ve en fazla ~14 ay önce olmalı."""
    s = _digits(tok.strip(".,;"))
    hi = date.fromisoformat(filed)
    lo = hi - timedelta(days=430)
    # eğik çizgi sık sık "1" okunuyor: 9124/2026, 91/24/2026, 19/15/2026 → 9/24, 9/24, 9/15
    variants = [s] + [s[:i] + "/" + s[i + 1:] for i, c in enumerate(s) if c == "1"] \
        + [s[:i] + s[i + 1:] for i, c in enumerate(s) if c == "1"]
    cands = []
    for v in variants:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", v)
        if not m:
            continue
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        cands += [(y, mo, d), (hi.year, mo, d), (hi.year - 1, mo, d)]   # 2028 → 2026 gibi yıl hatası
    for y, mo, d in cands:
        try:
            dt = date(y, mo, d)
        except ValueError:
            continue
        if lo <= dt <= hi:
            return dt.isoformat()
    return None


def parse_type(tok):
    t = tok.lower()
    if "exch" in t:
        return "E", 0
    if re.search(r"p?u?rc|urch|purc", t):
        return "P", 0
    if re.search(r"s[ae][l1i]|al[eo]", t):
        return "S", int("part" in t)
    return None, 0


def parse_amount(text):
    """'No S1,000.001 - $5.000,000' → ('$1,000,001 - $5,000,000', 1000001, 5000000)."""
    t = re.sub(r"(?<![A-Za-z])S(?=\s?[\d])", "$", text)
    if re.search(r"Over", t, re.I):
        nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\$\s?[\d.,\s]{4,}", t)]
        lo = (nums[0] + 1) if nums else 50000001
        return f"${lo - 1:,}+", lo, None
    nums = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\$\s?\d[\d.,\s]*\d", t) if re.sub(r"\D", "", n)]
    if not nums:
        return None, None, None
    lo = nums[0]
    best = min(BRACKETS, key=lambda b: abs(math.log10(max(lo, 1)) - math.log10(b[0])))
    lo, hi = best
    return (f"${lo:,} - ${hi:,}" if hi else f"${lo - 1:,}+"), lo, hi


def fallback_types(pdf_text):
    """PDF'in kendi (hatalı) metin katmanından satır no → işlem türü. Vision'ın kaçırdığı tür hücreleri için."""
    out = {}
    for line in pdf_text.splitlines():
        m = re.match(r"\s*(\d{1,3})\s+(.*)", line)
        if not m:
            continue
        w = TYPE_WORD.search(m.group(2))
        if w and parse_type(w.group(0))[0]:
            out.setdefault(int(m.group(1)), parse_type(w.group(0)))
    return out


def rows_from_ocr(tokens, filed, fallback=None):
    """Sayfa sayfa: tarih hücreleri satır çapası olur; aynı yükseklikteki tür/tutar ve
    bir sonraki satıra kadarki açıklama satırları birleştirilir."""
    fallback = fallback or {}
    out = []
    for p in sorted({t["p"] for t in tokens}):
        page = [t for t in tokens if t["p"] == p]
        hdr = lambda rx, d: next((t["x"] for t in page if rx.match(t["t"].strip())), d)
        type_x, date_x, amt_x = hdr(TYPE_HDR, 0.59), hdr(DATE_HDR, 0.69), hdr(AMT_HDR, 0.86)
        desc_x = hdr(DESC_HDR, 0.14) - 0.02   # açıklama sütununun solu; daha solu satır numarası
        notif_x = date_x + 0.03   # "30 gün" sütunu tarihten hemen sonra başlar
        header_y = min((t["y"] for t in page if TYPE_HDR.match(t["t"].strip()) or DATE_HDR.match(t["t"].strip())),
                       default=0.15)
        # tarih sütunu: sayfanın sağ yarısındaki tarihlerin ortanca x'i (sayfadan sayfaya kayabiliyor)
        dates = [t for t in page if 0.5 <= t["x"] < 0.85 and t["y"] > header_y - 0.01 and DATE_TOKEN.match(t["t"].strip())]
        if not dates:
            continue
        mid = sorted(t["x"] for t in dates)[len(dates) // 2]
        anchors = sorted([t for t in dates if abs(t["x"] - mid) < 0.03], key=lambda t: t["y"])
        notif_x = mid + 0.05
        for i, a in enumerate(anchors):
            y0 = a["y"] - 0.008
            y1 = anchors[i + 1]["y"] - 0.008 if i + 1 < len(anchors) else a["y"] + 0.06
            band = [t for t in page if y0 <= t["y"] < y1]
            same = [t for t in band if abs(t["y"] - a["y"]) < 0.012]
            # tür hücresi: tarihin solunda, satır hizasında, "purchase/sale/exchange"e benzeyen kısa kelime
            typ_tok = next((t for t in sorted(same, key=lambda t: -t["x"]) if 0.45 <= t["x"] < a["x"] - 0.01
                            and len(t["t"]) <= 22 and parse_type(t["t"])[0]), None)
            typ = typ_tok["t"] if typ_tok else ""
            desc = " ".join(t["t"] for t in sorted([t for t in band if desc_x <= t["x"] < a["x"] - 0.01
                                                   and t is not typ_tok], key=lambda t: (round(t["y"], 3), t["x"])))
            if not typ:   # Vision tür kelimesini açıklamayla tek parça okumuş olabilir: "ROCKWELL AUTOMATION INC salo"
                m = TYPE_WORD.search(desc)
                if m:
                    typ, desc = m.group(0), (desc[:m.start()] + " " + desc[m.end():])
            amt = " ".join(t["t"] for t in sorted([t for t in band if t["x"] >= notif_x - 0.01
                                                   and t["y"] < a["y"] + 0.025], key=lambda t: (t["y"], t["x"])))
            kind, partial = parse_type(typ)
            row_no = next((int(t["t"]) for t in same if t["x"] < desc_x and re.fullmatch(r"\d{1,3}", t["t"].strip())), None)
            if not kind and row_no in fallback:
                kind, partial = fallback[row_no]
            desc = re.sub(r"^\s*\d{1,3}\s+", "", desc) if desc else desc
            d = parse_date(a["t"], filed)
            amount, lo, hi = parse_amount(amt)
            desc = re.sub(r"\s+", " ", desc).strip(" -")
            if not kind or not d or not desc:
                continue
            out.append({"asset": desc, "type": kind, "partial": partial, "tx_date": d,
                        "amount": amount, "amt_lo": lo, "amt_hi": hi, "late": int(bool(re.match(r"\s*Y", amt)))})
    return out


# ---------------------------------------------------------------- varlık adı → sembol

BOND_RE = re.compile(r"\d\s?%|\bDUE\b|\bDu[eo]\b|TREAS(?!.*ETF)|\bT-BILL|\bBILL\b|\bNOTES?\b(?!.*ETF)|"
                     r"\bREV\b|\bCNTY\b|SCH DIST|\bMUN\b|\bGO\b|\bB/E\b|\bBDS?\b|AUTH\b|\bCTF\b", re.I)
NOISE = re.compile(r"\b(UNSOLICITED|SOLICITED|COM|CL [A-C]|CLASS [A-C]|SHS|SHARES|ORD|ADR|NEW|ISIN.*)$", re.I)
US_SYMBOL = re.compile(r"^[A-Z]{1,5}(?:-[A-Z])?$")


def asset_kind(name):
    if "ETF" in name.upper() or "FUND" in name.upper() and "INDEX" in name.upper():
        return "EF"
    if BOND_RE.search(name):
        return "GS"
    return "ST"


def _clean(name):
    n = re.sub(r"[^\w&.\-/ ]", " ", name)
    for _ in range(3):
        n = NOISE.sub("", n.strip()).strip()
    return re.sub(r"\s+", " ", n)[:80]


SYN = {"CORPORATION": "CORP", "COMPANY": "CO", "COMPANIES": "COS", "INCORPORATED": "INC", "HOLDINGS": "HLDGS",
       "HOLDING": "HLDGS", "HLDG": "HLDGS", "FINANCIAL": "FINL", "INTERNATIONAL": "INTL", "SERVICES": "SVCS",
       "SERVICE": "SVC", "INDUSTRIES": "INDS", "PROPERTIES": "PPTYS", "REALTY": "RLTY", "TRUST": "TR", "GROUP": "GRP",
       "TECHNOLOGIES": "TECH", "TECHNOLOGY": "TECH", "SOLUTIONS": "SOLUTION", "MANAGEMENT": "MGMT", "MGT": "MGMT",
       "INVESTMENT": "INVT", "INVESTMENTS": "INVT", "MATERIALS": "MATLS", "PAYMENTS": "PMTS", "ENTERTAINMENT": "ENTMT",
       "INSTRUMENTS": "INSTRS", "PHARMACEUTICALS": "PHARMA", "PARTS": "PTS", "INDEMNITY": "INDTY",
       "LABORATORIES": "LABS", "COMMUNICATIONS": "COMMUNICATION", "SYSTEMS": "SYS", "AMERICA": "AMER",
       "AMERICAN": "AMERN", "RESOURCES": "RES", "ENERGY": "ENERGY", "PARTNERS": "PARTNERS", "MANUFACTURING": "MFG",
       "BANCORPORATION": "BANCORP", "LIMITED": "LTD", "PRODUCTS": "PRODS", "PRODUCT": "PRODS", "NATIONAL": "NATL",
       "ENTERPRISES": "ENTERPRISE", "WHOLESALE": "WHSL", "SCIENCES": "SCIENCE", "HEALTHCARE": "HEALTH", "MOTORS": "MTRS",
       "UNITED": "UTD", "STORES": "STORES", "RESTAURANTS": "RESTAURANT", "BRANDS": "BRANDS", "SOUTHERN": "SOUTHN"}
NOISE_TOK = {"INC", "CORP", "CO", "COS", "LTD", "PLC", "THE", "NEW", "DEL", "DE", "CLASS", "CL", "A", "B", "C", "F",
             "REIT", "COM", "UNSOLICITED", "SOLICITED", "SHS", "ORD", "SA", "NV", "AG", "LP", "LLC", "IRELAND", "N",
             "V", "COMMON", "STOCK", "SHARES", "ADR", "SPONSORED", "&", "AND", "HOLDINGS", "HLDGS", "GRP"}
_sec_idx = {}


def _seq(name):
    words = re.sub(r"[^A-Z0-9& ]", " ", (name or "").upper().replace("&AMP;", "&")).split()
    return [SYN.get(w, w) for w in words if SYN.get(w, w) not in NOISE_TOK]


def _toks(name):
    return frozenset(_seq(name))


def sec_name_match(name):
    """Broker kısaltmalı adı (DISNEY WALT CO, LILLY ELI & CO, IBM CORP) SEC şirket listesiyle eşleştirir.
    Kelime kümeleri aynıysa ya da biri diğerini kapsıyorsa (en az iki kelime) eşleşir; büyük şirket önceliklidir."""
    if not _sec_idx:
        if not sec._tickers:
            sec.load()
        by_cik = sec._tickers.get("by_cik") or {}
        exact, inv = {}, {}
        for info in sorted(by_cik.values(), key=lambda i: i["rank"]):
            if info["rank"] > 8000:
                continue
            t = _toks(info["name"])
            if not t:
                continue
            exact.setdefault(t, info["ticker"])
            for w in t:
                inv.setdefault(w, []).append((t, info["ticker"]))
        joined = {}
        for info in sorted(by_cik.values(), key=lambda i: i["rank"]):
            if info["rank"] <= 8000:
                joined.setdefault("".join(_seq(info["name"])), info["ticker"])
        _sec_idx.update(exact=exact, inv=inv, joined=joined)
    t = _toks(name)
    if not t:
        return None
    if len(t) == 1:   # "IBM CORP" gibi adı zaten sembol olanlar
        w = next(iter(t))
        if sec.ticker_info(w):
            return w
    joined = "".join(_seq(name))   # INTERCONTINENTALEXCHANGE ↔ INTERCONTINENTAL EXCHANGE
    if joined in _sec_idx["joined"]:
        return _sec_idx["joined"][joined]
    if t in _sec_idx["exact"]:
        return _sec_idx["exact"][t]
    rare = min(t, key=lambda w: len(_sec_idx["inv"].get(w, ())) or 10 ** 9)
    for st, ticker in _sec_idx["inv"].get(rare, ()):   # rank sırasında
        if (st <= t and len(st) >= 1 and len(t) - len(st) <= 1) or (t <= st and len(t) >= 2 and len(st) - len(t) <= 1):
            return ticker
    return None


def lookup_ticker(name):
    """Yahoo aramasıyla sembol; sonuç `name_map`te saklanır (bulunamayan da: tekrar tekrar sorulmasın)."""
    key = _clean(name).upper()
    hit = db.query("SELECT ticker FROM name_map WHERE name=?", (key,))
    if hit:
        return hit[0]["ticker"]
    ticker = sec_name_match(name) if "ETF" not in key else None   # önce SEC listesi (çevrimdışı, kısaltmaları tanır)
    if ticker:
        db.execute("INSERT OR REPLACE INTO name_map(name, ticker) VALUES(?, ?)", (key, ticker))
        return ticker
    try:
        r = requests.get("https://query2.finance.yahoo.com/v1/finance/search", headers=UA, timeout=20,
                         params={"q": key, "quotesCount": 6, "newsCount": 0})
        quotes = [q for q in r.json().get("quotes", []) if q.get("quoteType") in ("EQUITY", "ETF")]
        us = [q["symbol"] for q in quotes if US_SYMBOL.match(q.get("symbol", ""))]
        if us:
            ticker = us[0]
        else:   # yalnızca yabancı kotasyonlar dönerse (TJX.MX) kök sembol SEC listesinde var mı?
            for q in quotes:
                base = q.get("symbol", "").split(".")[0]
                if US_SYMBOL.match(base) and sec.ticker_info(base):
                    ticker = base
                    break
    except Exception:
        return None   # ağ hatası: saklama, sonra yeniden denensin
    db.execute("INSERT OR REPLACE INTO name_map(name, ticker) VALUES(?, ?)", (key, ticker))
    time.sleep(0.3)
    return ticker


# ---------------------------------------------------------------- senkron

def sync(stop=None, max_docs=30):
    """Yeni 278-T raporlarını okur. Dönen: (yeni işlemler, okunmayı bekleyen rapor sayısı)."""
    if not OCR_BIN.exists():
        raise RuntimeError("bin/kongre-ocr yok: macOS'ta `./ocr/derle.sh` çalıştırın (Başkan raporları yalnızca macOS'ta okunur)")
    reports = list_reports()
    done = {r["id"] for r in db.query("SELECT id FROM congress_docs WHERE chamber='W' AND error IS NULL")}
    todo = [r for r in reports if "W" + hashlib.sha1(r["url"].encode()).hexdigest()[:12] not in done]
    todo.sort(key=lambda r: r["filed"], reverse=True)
    new_tx, processed = [], 0
    tmp = Path(db.DB_PATH).parent / "oge_tmp.pdf"
    for rep in todo[:max_docs]:
        if stop and stop.is_set():
            break
        processed += 1
        doc_id = "W" + hashlib.sha1(rep["url"].encode()).hexdigest()[:12]
        member, party, title = PEOPLE[rep["person"]]
        txs, err = [], None
        try:
            r = requests.get(rep["url"], headers=UA, timeout=180)
            r.raise_for_status()
            tmp.write_bytes(r.content)
            from pypdf import PdfReader
            layer = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(tmp)).pages)
            txs = rows_from_ocr(ocr(tmp), rep["filed"], fallback_types(layer))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:300]
        finally:
            if tmp.exists():
                tmp.unlink()
        rows = []
        for i, t in enumerate(txs):
            kind = asset_kind(t["asset"])
            ticker = lookup_ticker(t["asset"]) if kind in ("ST", "EF") else None
            rows.append((f"{doc_id}-{i}", doc_id, "W", member, party, title, rep["filed"], t["tx_date"], None, "",
                         t["asset"], kind, ticker, t["type"], t["partial"], t["amount"], t["amt_lo"], t["amt_hi"],
                         rep["url"]))
        db.executemany("""INSERT OR REPLACE INTO congress_tx(id, doc_id, chamber, member, party, state_dst, filed, tx_date,
                          notified, owner, asset, asset_type, ticker, type, partial, amount, amt_lo, amt_hi, url)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        db.execute("""INSERT OR REPLACE INTO congress_docs(id, chamber, member, party, state_dst, filed, url,
                      electronic, n_tx, error) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (doc_id, "W", member, party, title, rep["filed"], rep["url"], 0, len(txs) if not err else None, err))
        new_tx += [dict(zip(("id", "doc_id", "chamber", "member", "party", "state_dst", "filed", "tx_date", "notified",
                             "owner", "asset", "asset_type", "ticker", "type", "partial", "amount", "amt_lo",
                             "amt_hi", "url"), r)) for r in rows]
    return new_tx, len(todo) - processed
