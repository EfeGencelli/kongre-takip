"""ABD Kongre üyelerinin hisse işlemleri (STOCK Act periyodik işlem raporları, PTR).

Temsilciler Meclisi: Clerk'in yıllık dizini (`{yıl}FD.zip` içindeki XML) ve elektronik PTR PDF'leri.
Elektronik raporların metni pypdf ile okunur, işlemler satır satır ayrıştırılır. Elle doldurulup
taranmış raporlar (DocID 2 ile başlamayanlar) okunamaz; yalnızca bağlantı olarak listelenir.

Senato (efdsearch.senate.gov) betik isteklerini bot korumasıyla engellediği için şimdilik yok;
tablolarda `chamber` sütunu ileride eklenebilsin diye var.

Notlar: işlemler 45 güne kadar gecikmeli bildirilir, tutarlar aralık olarak verilir ($1,001 - $15,000 gibi).
"""
import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime

import requests

from . import db

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kongre-takip"}
HOUSE = "https://disclosures-clerk.house.gov/public_disc"
LEGISLATORS = "https://unitedstates.github.io/congress-legislators/legislators-current.json"

ASSET_TYPES = {"ST": "Hisse", "OP": "Opsiyon", "EF": "ETF", "MF": "Yatırım fonu", "GS": "Devlet tahvili",
               "CS": "Şirket tahvili", "CT": "Kripto", "OT": "Diğer", "PS": "Hisse (özel)", "OI": "Diğer",
               "DS": "Hisse (yurtdışı)", "AB": "Varlık destekli", "HN": "Hedge fon", "PE": "Özel sermaye",
               "RE": "Gayrimenkul", "BA": "Banka hesabı", "IH": "Fon"}

# ---------------------------------------------------------------- PDF ayrıştırma

HEADER_LINES = {"ID Owner Asset Transaction", "Type", "Date Notification", "Date", "Amount Cap.", "Gains >", "$200?",
                "ID Owner Asset Transaction Type Date Notification Date Amount Cap. Gains > $200?"}
# "F      S     : New", "S          O : Moran Wealth IRA", "L       : US", "D          : ..." (yazı tipi harfleri yutuyor)
DETAIL_RE = re.compile(r"^[A-Z](?:\s+[A-Z])*\s+:(?:\s|$)")
TX_RE = re.compile(
    r"(?:\b(SP|JT|DC)\s+)?(\S.*?)\s*\[([A-Z]{2})\]\s*"
    r"(P|S \(partial\)|S|E)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}/\d{1,2}/\d{4})\s+"
    r"((?:Spouse/DC\s+)?Over\s+\$[\d,]+|\$[\d,]+\s*-\s*\$[\d,]+|\$[\d,]+)")
TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9]{0,5}(?:[.\-/$][A-Z0-9]{1,2})?)\)")
OWNERS = {"SP": "Eş", "JT": "Ortak", "DC": "Çocuk", "": "Kendisi"}


def _iso(mdY):
    m, d, y = mdY.split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _amount(s):
    nums = [float(x.replace(",", "").rstrip(".")) for x in re.findall(r"\$([\d,.]+)", s)]
    if not nums:
        return None, None
    if "Over" in s:
        return nums[0] + 1, None
    return nums[0], (nums[1] if len(nums) > 1 else nums[0])


TRIPLE_RE = re.compile(r"(?<![A-Za-z])(P|S \(partial\)|S|E)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}/\d{1,2}/\d{4})")
TYPE_RE = re.compile(r"\[([A-Z]{2})\]")
AMOUNT_RE = re.compile(r"(?:Spouse/DC\s+)?Over\s+\$[\d,]+|\$\d[\d,]*(?:\.\d+)?(?:\s*-(?:\s*\$\d[\d,]*)?)?")


def _record(owner, asset, atype, tx, d_tx, d_note, amount):
    asset = re.sub(r"\s+", " ", asset).strip(" -")
    tick = TICKER_RE.findall(asset)
    lo, hi = _amount(amount)
    return {
        "owner": owner or "", "asset": asset, "asset_type": atype,
        "ticker": tick[-1].replace("/", ".") if tick else None,
        "type": "S" if tx.startswith("S") else tx, "partial": int("partial" in tx),
        "tx_date": _iso(d_tx), "notified": _iso(d_note),
        "amount": re.sub(r"\s+", " ", amount).replace("Spouse/DC ", "").strip(), "amt_lo": lo, "amt_hi": hi,
    }


def _trim_lead(lines):
    """Parçanın başındaki, önceki işlemin açıklamasından taşan satırları atar. Varlık sütunu dar olduğundan
    ad satırları kısadır; tür kodunu ([ST]) ya da işlem tarihini içermeyen uzun satırlar açıklamadır."""
    key = next((i for i, l in enumerate(lines) if TYPE_RE.search(l) or TRIPLE_RE.search(l)), len(lines))
    start = 0
    for i in range(key):
        if len(lines[i]) > 60 or re.search(r"[.;:]$", lines[i]) and len(lines[i]) > 25:
            start = i + 1
    return lines[max(start, key - 5):]


def _chunk_record(lines):
    """Tek işlemlik metin parçası: parçalar sayfa sonunda bölünmüş olsa da (ad / tarih / tutar sırası karışık) okunur."""
    chunk = " ".join(_trim_lead(lines))
    t, k = TRIPLE_RE.search(chunk), TYPE_RE.search(chunk)
    if not t or not k:
        return None
    before, after = chunk[:t.start()], chunk[t.end():]
    amounts = AMOUNT_RE.findall(after)   # tutar sütunu tarihlerden sonra gelir
    amount = re.sub(r"\s+", " ", " ".join(a.strip() for a in amounts)).replace("- -", "-")
    rest = TYPE_RE.sub(" ", before + " " + AMOUNT_RE.sub(" ", after), count=1)
    owner = None
    m = re.search(r"(?:^|\s)(SP|JT|DC)\s+(?=[A-Z0-9])", rest)   # sahip kodu varlık adının başındadır
    if m:
        owner, rest = m.group(1), rest[m.end():]
    return _record(owner, rest, k.group(1), t.group(1), t.group(2), t.group(3), amount)


def parse_ptr_text(text):
    """Elektronik House PTR'nin metninden işlem listesi.

    Her işlemin ardından "Filing Status: New" gibi açıklama satırları gelir; metin bu satırlardan bölünür,
    her parça bir işlemdir. Bir parçada birden fazla işlem varsa (açıklamasız raporlar) satır deseniyle okunur."""
    text = text.replace("\x00", " ")
    chunks, cur, started = [], [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not started:
            started = line == "$200?" or line.endswith("Gains > $200?")
            continue
        if line.startswith("* For the complete list") or line.startswith("I CERTIFY"):
            break
        if not line or line in HEADER_LINES or line.startswith("Filing ID #"):
            continue   # sayfa sonu: işlem bir sonraki sayfada sürebilir
        if DETAIL_RE.match(line):
            if cur:
                chunks.append(cur)
            cur = []
            continue
        cur.append(line)
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        if len(TRIPLE_RE.findall(" ".join(c))) > 1:
            out += [_record(*m.groups()) for m in TX_RE.finditer("\n".join(c).replace("\n", " "))]
        else:
            r = _chunk_record(c)
            if r:
                out.append(r)
    return out


def parse_ptr_pdf(content):
    from pypdf import PdfReader   # yalnızca burada gerekli; kurulumda eklenir
    reader = PdfReader(io.BytesIO(content))
    return parse_ptr_text("\n".join((p.extract_text() or "") for p in reader.pages))


# ---------------------------------------------------------------- üye bilgisi (parti)

def _legislators():
    """Eyalet+bölge → (parti, ad). Haftada bir yenilenir."""
    cached = db.get_meta("congress_legislators")
    if cached and time.time() - cached.get("at", 0) < 7 * 86400:
        return cached["map"]
    try:
        rows = requests.get(LEGISLATORS, headers=UA, timeout=30).json()
    except Exception:
        return (cached or {}).get("map", {})
    m = {}
    for p in rows:
        t = p["terms"][-1]
        party = {"Democrat": "D", "Republican": "R", "Independent": "I"}.get(t.get("party"), (t.get("party") or "?")[:1])
        name = p["name"].get("official_full") or f"{p['name'].get('first')} {p['name'].get('last')}"
        if t["type"] == "rep":
            m[f"{t['state']}{int(t.get('district') or 0):02d}"] = [party, name]
        else:
            m[f"SEN:{t['state']}:{p['name'].get('last', '').lower()}"] = [party, name]
    db.set_meta("congress_legislators", {"at": time.time(), "map": m})
    return m


# ---------------------------------------------------------------- Temsilciler Meclisi

def _house_index(year):
    r = requests.get(f"{HOUSE}/financial-pdfs/{year}FD.zip", headers=UA, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read(f"{year}FD.xml"))
    out = []
    for m in root:
        if (m.findtext("FilingType") or "") != "P":
            continue
        g = lambda k: (m.findtext(k) or "").strip()
        name = " ".join(x for x in (g("First"), g("Last"), g("Suffix")) if x)
        try:
            filed = datetime.strptime(g("FilingDate"), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        out.append({"doc": g("DocID"), "member": name, "last": g("Last"), "state_dst": g("StateDst"),
                    "filed": filed, "year": year})
    return out


def sync_house(stop=None, max_docs=600, pause=0.25):
    """Yeni House PTR'lerini indirir ve ayrıştırır. Dönen: yeni işlemler (bildirim için)."""
    years = [date.today().year]
    if date.today().month <= 2:
        years.insert(0, date.today().year - 1)   # yıl başında geçen yılın son raporları da gelir
    done = {r["id"] for r in db.query("SELECT id FROM congress_docs WHERE chamber='H' AND error IS NULL")}
    leg = _legislators()
    todo = []
    for y in years:
        todo += [d for d in _house_index(y) if f"H{d['doc']}" not in done]
    todo.sort(key=lambda d: d["filed"], reverse=True)   # en yeni önce
    new_tx, processed = [], 0
    for d in todo[:max_docs]:
        if stop and stop.is_set():
            break
        processed += 1
        doc_id = f"H{d['doc']}"
        electronic = d["doc"].startswith("2")
        url = f"{HOUSE}/ptr-pdfs/{d['year']}/{d['doc']}.pdf"   # taranmış raporlar da burada
        party, full = (leg.get(d["state_dst"]) or [None, None])
        if full and d["last"].split()[-1].lower() not in full.lower():
            party, full = None, None   # bölgenin bugünkü temsilcisi başka biri (görevden ayrılmış üye)
        txs, err = [], None
        if electronic:
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, timeout=120)
                r.raise_for_status()
                txs = parse_ptr_pdf(r.content)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
            time.sleep(pause)
        member = full or d["member"]   # resmi ad (Clerk dizinindeki ad bazen karışık: "John J Mr McGuire III")
        rows = []
        for i, t in enumerate(txs):
            rows.append((f"{doc_id}-{i}", doc_id, "H", member, party, d["state_dst"], d["filed"], t["tx_date"],
                         t["notified"], t["owner"], t["asset"], t["asset_type"], t["ticker"], t["type"], t["partial"],
                         t["amount"], t["amt_lo"], t["amt_hi"], url))
        db.executemany("""INSERT OR REPLACE INTO congress_tx(id, doc_id, chamber, member, party, state_dst, filed, tx_date,
                          notified, owner, asset, asset_type, ticker, type, partial, amount, amt_lo, amt_hi, url)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        db.execute("""INSERT OR REPLACE INTO congress_docs(id, chamber, member, party, state_dst, filed, url,
                      electronic, n_tx, error) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (doc_id, "H", member, party, d["state_dst"], d["filed"], url, int(electronic),
                    len(txs) if electronic and not err else None, err))
        new_tx += [dict(zip(("id", "doc_id", "chamber", "member", "party", "state_dst", "filed", "tx_date", "notified",
                             "owner", "asset", "asset_type", "ticker", "type", "partial", "amount", "amt_lo", "amt_hi",
                             "url"), r)) for r in rows]
    return new_tx, len(todo) - processed


PTR_URL_RE = re.compile(r"^(https://disclosures-clerk\.house\.gov/public_disc/ptr-pdfs/\d{4}/\d+\.pdf"
                        r"|https://extapps2\.oge\.gov/201/Presiden\.nsf/PAS\+Index/[0-9A-F]+/\$FILE/[^?#]+\.pdf)$")


def is_ptr_url(url):
    return bool(PTR_URL_RE.match(url or ""))


def fetch_pdf(url):
    if not is_ptr_url(url):
        raise ValueError("Geçersiz rapor adresi")
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    return r.content


def sync(stop=None):
    """Dönen: (yeni işlemler, okunmayı bekleyen rapor sayısı)."""
    return sync_house(stop=stop)
