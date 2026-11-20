# Kongre Takip

ABD Temsilciler Meclisi üyelerinin ve Başkanın hisse işlemlerini resmi kaynaklardan toplar. İşlemden sonra
hissenin S&P 500'e göre ne yaptığını hesaplar: **"Politikacılar piyasayı yeniyor mu?"**

- **Son işlemler:** kim, neyi, ne zaman, hangi tutar aralığında aldı/sattı; kaç gün geç bildirdi; o günden bu yana
  hisse ve S&P 500 getirisi.
- **Piyasayı yendi mi?:** kişi ve parti bazında karne (alım farkı, satış zamanlaması, isabet oranı).
  Başkanın işlemleri ayrı grupta.
- **Hisse bazında / Üye bazında:** en çok işlem gören hisseler, en aktif kişiler.
- **★ Ünlüler:** Trump, Pelosi, Crenshaw, Gottheimer… tek tıkla.
- **Raporlar:** kaynak PDF'ler; satıra tıklayınca orijinal belge açılır.

## Kaynaklar

| Kaynak | Ne | Nasıl okunuyor |
|---|---|---|
| [House Clerk](https://disclosures-clerk.house.gov/FinancialDisclosure) | Meclis üyelerinin periyodik işlem raporları (PTR) | Yıllık XML dizini + elektronik PDF'ler (pypdf) |
| [OGE](https://www.oge.gov) | Başkanın 278-T işlem raporları | Taranmış PDF → macOS Vision metin tanıma |
| [congress-legislators](https://github.com/unitedstates/congress-legislators) | Parti ve resmi adlar | JSON |
| SEC `company_tickers.json` + Yahoo | Şirket adı → sembol, günlük kapanışlar | — |

Senato yok: efdsearch.senate.gov otomatik istekleri bot korumasıyla engelliyor.

## Kurulum

Python 3.9+ yeterli.

```bash
git clone <bu depo> && cd kongre-takip
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./ocr/derle.sh          # yalnızca macOS: Başkanın raporlarını okumak için (Xcode komut satırı araçları gerekir)
python app.py           # http://localhost:8765
```

İlk açılışta veriler toplanır (Meclis birkaç dakika, Başkanın raporları ilk seferde 30–60 dakika); sayfa veri geldikçe dolar.
Sonra saatte bir kendiliğinden güncellenir. Yalnızca veriyi güncellemek için: `python -m kongre.sync`.

Sayfa açılmazsa (ör. `ERR_UNSAFE_PORT`): `KONGRE_PORT` ile başka bir kapı seçin; 5060, 5061, 6000 gibi kapıları
Chrome güvenlik gereği açmaz.

macOS dışında `./ocr/derle.sh` çalışmaz; uygulama Başkanın raporlarını atlar, Meclis kısmı aynen çalışır.

> **Yalnızca kendi bilgisayarınızda çalıştırın.** Uygulama kişisel kullanım için yazıldı: yalnızca `localhost`
> üzerinden erişilir, giriş ekranı ya da kullanıcı hesabı yoktur. İnternete açık bir sunucuya kurmayın.

### Yapay zeka asistanıyla kurulum

Depoda bir Claude Code skill'i var (`.claude/skills/kongre-takip/SKILL.md`). Depoyu indirip klasörde Claude Code'a
"Kongre Takip'i kur ve aç" demeniz yeterli; kurulum, çalıştırma ve "Pelosi son ay ne aldı?" gibi soruları
yanıtlama adımları orada yazılı. Skill yalnızca bu klasörde çalışır.

### Ayarlar (isteğe bağlı)

- `KONGRE_SEC_UA="Ad Soyad eposta@ornek.com"`: SEC, otomatik isteklerde iletişim bilgisi ister (şirket listesi için).
- `KONGRE_PORT` (varsayılan 8765), `KONGRE_VERI` (veri klasörü, varsayılan `./veri`), `KONGRE_DAKIKA` (güncelleme aralığı).
- Ünlüler listesi: `ayarlar.ornek.json` dosyasını `ayarlar.json` adıyla kopyalayıp düzenleyin.

## Hesap nasıl yapılıyor

- Raporlarda işlem fiyatı yok; **işlem günündeki kapanış** kullanılır (Yahoo, bölünme ve temettü düzeltmeli).
- **Fark** = hisse getirisi − aynı dönemde S&P 500 (SPY) getirisi, puan olarak.
  Alımda artı iyidir; satışta eksi iyidir (sattıktan sonra hisse piyasanın gerisinde kalmış).
- Tutarlar aralık olarak bildirildiği için ($1,001–$15,000 gibi) her işlem **eşit ağırlıkta** sayılır.
- Karneye hisse ve ETF'ler girer; opsiyon ve tahviller girmez.
- "Bugüne kadar" yerine 30/90/180 gün sonrası seçilebilir (farklı tutma sürelerini eşitlemek için).

## Bilinen sınırlar

- İşlemler 45 güne kadar gecikmeli bildirilir: buradaki getiriler kopyalanabilir getiriler değildir.
- Elle doldurulup taranmış Meclis raporları okunamaz; yalnızca bağlantı olarak listelenir.
- Başkanın raporları taranmış PDF'tir: metin tanıma satırların yaklaşık %85'ini okuyabiliyor; şirket adlarının
  bir kısmı sembole çevrilemiyor (bunların getirisi hesaplanmaz). Kaynak PDF her satırdan açılabilir.
- İyi ya da kötü zamanlama içeriden bilgi kullanıldığının kanıtı değildir.

Yatırım tavsiyesi değildir.

## Lisans

MIT
