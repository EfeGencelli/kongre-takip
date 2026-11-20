"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (p) => { const r = await fetch(p); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); };
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem("kt." + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("kt." + k, JSON.stringify(v)); } catch { /* yoksay */ } } };

const MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
const dShort = (iso) => { if (!iso) return ""; const d = new Date(iso.slice(0, 10) + "T12:00:00"); return `${String(d.getDate()).padStart(2, "0")} ${MONTHS[d.getMonth()]} '${String(d.getFullYear()).slice(2)}`; };
const num = (v, d = 0) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d });
const int = (v) => v == null ? "" : Math.round(v).toLocaleString("en-US");
const pct = (v) => v == null ? "—" : `${v > 0 ? "+" : ""}${num(v, 1)}%`;
const ret = (v) => v == null ? '<span class="muted">—</span>' : `<span class="${v >= 0 ? "pos" : "neg"}">${pct(v)}</span>`;
function edge(v, isSale) {
  if (v == null) return '<span class="muted">—</span>';
  const good = isSale ? v < 0 : v > 0;
  return `<b class="${good ? "pos" : "neg"}">${v > 0 ? "+" : ""}${num(v, 1)}</b>`;
}
const PARTY = { D: "Demokrat", R: "Cumhuriyetçi", I: "Bağımsız" };
const party = (p) => p ? `<span class="tag ${p.toLowerCase()}" title="${PARTY[p] || p}">${p}</span>` : "";
const star = (r) => r.famous ? '<span class="star" title="Ünlü">★</span> ' : "";
const TYPE = { P: ["Alım", "buy"], S: ["Satış", "sale"], E: ["Takas", ""] };
const OWNER = { SP: "Eş", JT: "Ortak", DC: "Çocuk", "": "Kendisi" };

const st = store.get("st", { view: "list", party: "", days: 30, type: "PS", min: 0, horizon: "", famous: false, all: false, q: "" });
const out = $("#out");

function delay(r) {
  if (!r.tx_date || !r.filed) return "";
  const d = Math.round((new Date(r.filed) - new Date(r.tx_date.slice(0, 10))) / 864e5);
  return `<span class="${d > 45 ? "late" : ""}" title="İşlem ile bildirim arası (yasal sınır 45 gün)">${d} gün</span>`;
}

async function load() {
  store.set("st", st);
  out.innerHTML = `<div class="empty">Yükleniyor…</div>`;
  try {
    if (st.view === "score") return await drawScore();
    if (st.view === "docs") return await drawDocs();
    const p = new URLSearchParams({ view: st.view, party: st.party, days: st.days, type: st.type, min: st.min,
      horizon: st.horizon, famous: st.famous ? 1 : 0, assets: st.all ? "all" : "stocks", q: st.q });
    const rows = await api("/api/trades?" + p);
    $("#count").textContent = `${rows.length} kayıt`;
    if (!rows.length) { out.innerHTML = `<div class="empty">${emptyText()}</div>`; return; }
    if (st.view === "ticker") return drawTickers(rows);
    if (st.view === "member") return drawMembers(rows);
    drawList(rows);
  } catch (e) {
    out.innerHTML = `<div class="empty">Hata: ${esc(e.message)}</div>`;
  }
}

function drawList(rows) {
  out.innerHTML = `<table><thead><tr><th>Sembol</th><th>Varlık</th><th>Kişi</th><th>Parti</th><th>Sahibi</th><th>İşlem tarihi</th><th>İşlem</th>
    <th class="num">Tutar ($)</th><th class="num" title="İşlem günü kapanışından ${st.horizon ? st.horizon + " gün sonrasına" : "bugüne"}">Sonra</th>
    <th class="num" title="Aynı dönemde S&P 500 (SPY)">S&P</th><th class="num" title="Hisse eksi S&P 500 (puan). Satışta eksi değer iyi zamanlamadır.">Fark</th>
    <th class="num">Gecikme</th><th class="num">Bildirim</th></tr></thead><tbody>
    ${rows.map((r) => `<tr class="click ${(TYPE[r.type] || ["", ""])[1]}" data-url="${esc(r.url)}">
      <td><span class="tk">${esc(r.ticker || "—")}</span></td>
      <td class="wrap" title="${esc(r.asset)}">${esc(r.asset)}${r.asset_type === "OP" ? ' <span class="tag">opsiyon</span>' : ""}</td>
      <td>${star(r)}${esc(r.member)}</td><td>${party(r.party)} <span class="muted">${esc(r.state_dst || "")}</span></td>
      <td class="muted">${OWNER[r.owner || ""] ?? esc(r.owner)}</td><td>${dShort(r.tx_date)}</td>
      <td>${(TYPE[r.type] || [r.type])[0]}${r.partial ? ' <span class="tag">kısmi</span>' : ""}</td>
      <td class="num">${esc(r.amount || "—")}</td><td class="num">${ret(r.ret)}</td><td class="num">${ret(r.spy_ret)}</td>
      <td class="num">${edge(r.excess, r.type === "S")}</td><td class="num">${delay(r)}</td><td class="num muted">${dShort(r.filed)}</td></tr>`).join("")}
    </tbody></table>`;
  sortable();
}

function drawTickers(rows) {
  out.innerHTML = `<table><thead><tr><th>Sembol</th><th>Varlık</th><th class="num">Alan kişi</th><th class="num">Satan kişi</th>
    <th class="num">Alım</th><th class="num">Satış</th><th class="num" title="Aralık alt sınırları toplamı">Alım (en az $)</th><th class="num">Satış (en az $)</th><th>Kişiler</th><th class="num">Son bildirim</th></tr></thead><tbody>
    ${rows.map((r) => `<tr class="${r.n_buyers > r.n_sellers ? "buy" : r.n_sellers > r.n_buyers ? "sale" : ""}">
      <td><span class="tk">${esc(r.ticker)}</span></td><td class="wrap" title="${esc(r.asset)}">${esc(r.asset)}</td>
      <td class="num"><b>${r.n_buyers}</b></td><td class="num"><b>${r.n_sellers}</b></td><td class="num">${r.n_buys}</td><td class="num">${r.n_sales}</td>
      <td class="num">${int(r.buy_lo)}</td><td class="num">${int(r.sale_lo)}</td>
      <td class="wrap muted" title="${esc(r.members)}">${esc((r.members || "").split(",").slice(0, 3).join(", "))}</td><td class="num muted">${dShort(r.last_filed)}</td></tr>`).join("")}
    </tbody></table>`;
  sortable();
}

function drawMembers(rows) {
  out.innerHTML = `<table><thead><tr><th>Kişi</th><th>Parti</th><th>Bölge</th><th class="num">İşlem</th><th class="num">Alım</th><th class="num">Satış</th>
    <th class="num">Alım (en az $)</th><th class="num">Satış (en az $)</th><th class="num">Rapor</th><th>Semboller</th><th class="num">Son bildirim</th></tr></thead><tbody>
    ${rows.map((r) => `<tr class="click" data-member="${esc(r.member)}" title="Bu kişinin işlemlerini göster">
      <td>${star(r)}${esc(r.member)}</td><td>${party(r.party)}</td><td class="muted">${esc(r.state_dst || "")}</td>
      <td class="num"><b>${r.n_tx}</b></td><td class="num pos">${r.n_buys}</td><td class="num neg">${r.n_sales}</td>
      <td class="num">${int(r.buy_lo)}</td><td class="num">${int(r.sale_lo)}</td><td class="num">${r.n_docs}</td>
      <td class="wrap muted">${esc((r.tickers || "").split(",").slice(0, 8).join(", "))}</td><td class="num muted">${dShort(r.last_filed)}</td></tr>`).join("")}
    </tbody></table>`;
  sortable();
}

async function drawScore() {
  const days = Math.max(st.days, 90);
  const d = await api("/api/scorecard?" + new URLSearchParams({ days, party: st.party, horizon: st.horizon, famous: st.famous ? 1 : 0 }));
  $("#count").textContent = `${d.n_priced}/${d.n_rows} işlem fiyatlandı`;
  if (!d.n_priced) { out.innerHTML = `<div class="empty">Fiyat geçmişi henüz inmedi. Birkaç dakika sonra tekrar bak.</div>`; return; }
  const label = { Hepsi: "Kongre · tüm alımlar", D: "Demokratlar", R: "Cumhuriyetçiler", W: "Beyaz Saray (Başkan)" };
  const hz = st.horizon ? `${st.horizon} gün sonra` : "bugüne kadar";
  out.innerHTML = `<div class="note">Son ${days} günde yapılan hisse ve ETF alım/satımları · getiri işlem günü kapanışından ${hz} · eşit ağırlıklı · en az 3 işlemi olanlar</div>
    <div class="cards">${d.summary.filter((g) => g.n).map((g) => `<div class="card"><div class="k">${label[g.group]} · ${g.n} alım</div>
      <div class="v ${g.edge >= 0 ? "pos" : "neg"}">${g.edge > 0 ? "+" : ""}${num(g.edge, 1)} puan</div>
      <div class="k">Hisse ${pct(g.ret)} · S&P ${pct(g.spy)} · isabet %${g.hit}</div></div>`).join("")}</div>
    <table><thead><tr><th>Kişi</th><th>Parti</th><th class="num">Alım</th><th class="num">Satış</th><th class="num">Alım getirisi</th><th class="num">S&P</th>
      <th class="num" title="Alımlarda hisse eksi S&P (puan)">Alım farkı</th><th class="num">Alım isabeti</th>
      <th class="num" title="Satışlarda S&P eksi hisse: artı ise sattıktan sonra hisse geride kalmış">Satış farkı</th><th class="num">Toplam fark</th><th class="num">İsabet</th></tr></thead><tbody>
    ${d.members.map((m) => `<tr class="click" data-member="${esc(m.member)}">
      <td>${star(m)}${esc(m.member)} <span class="muted">${esc(m.state_dst || "")}</span></td><td>${party(m.party)}</td>
      <td class="num">${m.n_buys}</td><td class="num">${m.n_sales}</td><td class="num">${ret(m.buy_ret)}</td><td class="num">${ret(m.buy_spy)}</td>
      <td class="num">${ret(m.buy_edge)}</td><td class="num">${m.buy_hit == null ? "—" : "%" + m.buy_hit}</td><td class="num">${ret(m.sale_edge)}</td>
      <td class="num"><b class="${m.edge >= 0 ? "pos" : "neg"}">${m.edge > 0 ? "+" : ""}${num(m.edge, 1)}</b></td><td class="num">%${m.hit}</td></tr>`).join("")}
    </tbody></table>
    <div class="note">Raporlarda fiyat yok; işlem günündeki kapanış kullanılır. Tutarlar aralık olduğu için her işlem eşit sayılır. Opsiyon ve tahviller dahil değil.
      Başkanın işlemleri ayrı grupta, Kongre ortalamasına girmez. Bildirimler 45 güne kadar geciktiği için bu getiriler kopyalanabilir değildir.</div>`;
  sortable();
}

async function drawDocs() {
  const docs = (await api("/api/reports?days=" + st.days)).filter((d) => (!st.party || d.party === st.party) && (!st.q || d.member.toLowerCase().includes(st.q.toLowerCase())));
  $("#count").textContent = `${docs.length} rapor`;
  if (!docs.length) { out.innerHTML = `<div class="empty">${emptyText()}</div>`; return; }
  out.innerHTML = `<table><thead><tr><th>Kişi</th><th>Parti</th><th>Bölge</th><th class="num">İşlem</th><th>Biçim</th><th class="num">Bildirim</th></tr></thead><tbody>
    ${docs.map((d) => `<tr class="click" data-url="${esc(d.url)}"><td>${esc(d.member)}</td><td>${party(d.party)}</td><td class="muted">${esc(d.state_dst || "")}</td>
      <td class="num">${d.n_tx ?? "—"}</td><td class="muted">${d.chamber === "W" ? "OGE 278-T · metin tanıma" : d.electronic ? "elektronik" : "taranmış (elle)"}${d.error ? ` · <span class="neg" title="${esc(d.error)}">okunamadı</span>` : ""}</td>
      <td class="num muted">${dShort(d.filed)}</td></tr>`).join("")}</tbody></table>`;
  sortable();
}

function emptyText() {
  return window._status?.running ? "Veriler toplanıyor… İlk güncelleme birkaç dakika sürer, sayfa kendiliğinden yenilenir." : "Bu filtrelerle kayıt yok.";
}

// sütun başlığına tıkla: sırala (tarih, sayı, metin)
function sortable() {
  $$("th", out).forEach((th, i) => th.onclick = () => {
    const tb = th.closest("table").tBodies[0];
    const dir = th.dataset.dir === "desc" ? 1 : -1; th.dataset.dir = dir === 1 ? "asc" : "desc";
    const val = (tr) => { const t = tr.cells[i]?.textContent.trim() || ""; const n = parseFloat(t.replace(/[^0-9.\-+]/g, ""));
      const m = t.match(/^(\d{2}) (\S{3}) '(\d{2})$/); if (m) return new Date(2000 + +m[3], MONTHS.indexOf(m[2]), +m[1]).getTime();
      return /\d/.test(t) && !isNaN(n) && !/[a-zğüşıöç]{3}/i.test(t.replace(/gün|kayıt/g, "")) ? n : t; };
    [...tb.rows].sort((a, b) => { const x = val(a), y = val(b); return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "tr")) * dir; })
      .forEach((r) => tb.appendChild(r));
  });
}

out.addEventListener("click", (e) => {
  const m = e.target.closest("[data-member]");
  if (m) { st.q = m.dataset.member; st.view = "list"; $("#f-q").value = st.q; syncButtons(); load(); return; }
  const u = e.target.closest("[data-url]");
  if (u && u.dataset.url) window.open(u.dataset.url, "_blank", "noopener");
});

function syncButtons() {
  $$("#views button").forEach((b) => b.classList.toggle("on", b.dataset.view === st.view));
  $$('[data-chips="party"] button').forEach((b) => b.classList.toggle("on", b.dataset.v === st.party));
  $$('[data-chips="days"] button').forEach((b) => b.classList.toggle("on", +b.dataset.v === +st.days));
  $("#f-type").value = st.type; $("#f-min").value = String(st.min); $("#f-horizon").value = st.horizon;
  $("#f-famous").checked = st.famous; $("#f-all").checked = st.all; $("#f-q").value = st.q;
}
$$("#views button").forEach((b) => b.onclick = () => { st.view = b.dataset.view; syncButtons(); load(); });
$$('[data-chips="party"] button').forEach((b) => b.onclick = () => { st.party = b.dataset.v; syncButtons(); load(); });
$$('[data-chips="days"] button').forEach((b) => b.onclick = () => { st.days = +b.dataset.v; syncButtons(); load(); });
$("#f-type").onchange = (e) => { st.type = e.target.value; load(); };
$("#f-min").onchange = (e) => { st.min = +e.target.value; load(); };
$("#f-horizon").onchange = (e) => { st.horizon = e.target.value; load(); };
$("#f-famous").onchange = (e) => { st.famous = e.target.checked; load(); };
$("#f-all").onchange = (e) => { st.all = e.target.checked; load(); };
let qt; $("#f-q").oninput = (e) => { clearTimeout(qt); qt = setTimeout(() => { st.q = e.target.value.trim(); load(); }, 250); };

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const wasRunning = window._status?.running;
    window._status = s;
    $("#status").innerHTML = `${num(s.n_tx)} işlem · son bildirim ${dShort(s.last_filed)}<br>` +
      (s.running ? `güncelleniyor: ${esc(s.step || "")}` : s.error ? `<span class="neg" title="${esc(s.error)}">güncelleme hatası</span>` : `son güncelleme ${esc(s.last || "—")}`) +
      ` <button id="refresh">Şimdi güncelle</button>`;
    $("#refresh").onclick = async () => { await fetch("/api/refresh", { method: "POST" }); setTimeout(refreshStatus, 500); };
    if (wasRunning && !s.running) load();   // ilk güncelleme bitti: listeyi tazele
  } catch { /* sunucu kapalı */ }
}
syncButtons();
load();
refreshStatus();
setInterval(refreshStatus, 10000);
