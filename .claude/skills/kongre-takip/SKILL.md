---
name: kongre-takip
description: Kongre Takip'i kurar ve çalıştırır; ABD Kongre üyelerinin ve Başkanın hisse işlemlerini, işlemden sonra S&P 500'e göre performansı gösterir. Kullanıcı "Kongre Takip'i kur", "kongre işlemlerini göster", "Pelosi / Trump ne aldı", "politikacılar piyasayı yendi mi" dediğinde kullan.
---

# Kongre Takip

Bu depo tek başına çalışan küçük bir web uygulamasıdır (Python + Flask). Veriyi yalnızca resmi, herkese açık
kaynaklardan çeker (House Clerk, OGE, SEC, Yahoo). Hiçbir hesap, API anahtarı ya da şifre gerektirmez.

## Kurulum (kullanıcının bilgisayarında, depo klasöründe)

1. Python 3.9+ olduğunu kontrol et: `python3 --version`.
2. Sanal ortam ve paketler:
   ```bash
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```
3. Yalnızca macOS'ta, Başkanın taranmış raporlarını okumak için: `./ocr/derle.sh`
   (Xcode komut satırı araçları gerekir; yoksa bu adımı atla, Meclis kısmı yine çalışır).
4. İsteğe bağlı: `ayarlar.ornek.json` → `ayarlar.json` kopyala (Ünlüler listesi).

## Çalıştırma

```bash
./venv/bin/python app.py
```

Ardından kullanıcıya http://localhost:5060 adresini aç / ver. İlk açılışta veri toplanır (Meclis birkaç dakika,
Başkanın raporları 10–20 dakika); sayfa kendiliğinden dolar. Sunucu açık kaldıkça saatte bir güncellenir.
Sunucuyu arka planda başlatıyorsan kullanıcıya nasıl durduracağını söyle.

Yalnızca veriyi güncellemek: `./venv/bin/python -m kongre.sync`

## Soruları yanıtlamak

Sunucu çalışırken veriyi JSON olarak okuyabilirsin (tarayıcı açmadan):

- `GET /api/trades?days=30&famous=1` — son işlemler (`view=ticker` hisse bazında, `view=member` kişi bazında;
  `party=D|R`, `type=P|S`, `q=Pelosi`, `horizon=30|90|180`)
- `GET /api/scorecard?days=90` — "Piyasayı yendi mi?" karnesi (`summary` grupları: Hepsi, D, R, W=Başkan)
- `GET /api/reports?days=30` — kaynak raporlar (PDF bağlantıları)
- `GET /api/status` — güncelleme durumu

Sunucu kapalıysa SQLite'tan da okunabilir: `veri/kongre.db`, tablo `congress_tx`
(chamber: H = Temsilciler Meclisi, W = Beyaz Saray).

Yanıtlarken: tutarlar aralıktır; işlemler 45 güne kadar gecikmeli bildirilir; getiri işlem günü kapanışından
ölçülür; iyi/kötü zamanlama içeriden bilgi kullanıldığının kanıtı değildir. Yatırım tavsiyesi verme.

## Sınırlar

- Bu skill yalnızca bu depo klasöründe çalışır; başka klasörlere, hesaplara ya da servislere dokunmaz.
- Senato verisi yok (efdsearch.senate.gov otomatik erişimi engelliyor).
