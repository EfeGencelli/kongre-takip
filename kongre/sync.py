"""Verileri günceller: Temsilciler Meclisi raporları, Başkanın raporları (macOS) ve fiyat geçmişi.

Komut satırından:  python -m kongre.sync
Sunucu (app.py) bunu arka planda saatte bir kendisi çalıştırır.
"""
import sys
import threading
import time
import traceback

from . import db, house, returns, whitehouse

status = {"running": False, "last": None, "error": None, "remaining": None, "step": None}


def run(stop=None, log=print):
    status.update(running=True, error=None)
    try:
        status["step"] = "Temsilciler Meclisi raporları"
        new, rem = house.sync(stop=stop)
        log(f"Meclis: {len(new)} yeni işlem, {rem} rapor bekliyor")
        try:
            status["step"] = "Başkanın raporları (metin tanıma)"
            w_new, w_rem = whitehouse.sync(stop=stop)
            log(f"Beyaz Saray: {len(w_new)} yeni işlem, {w_rem} rapor bekliyor")
            rem += w_rem
        except Exception as e:   # macOS dışı ya da OCR aracı derlenmemiş: Meclis verisi yine çalışır
            log(f"Beyaz Saray atlandı: {e}")
        status["step"] = "Fiyat geçmişi"
        done, total = returns.sync(stop=stop)
        log(f"Fiyatlar: {done}/{total} hisse güncellendi")
        status.update(remaining=rem or None, last=time.strftime("%Y-%m-%d %H:%M"))
    except Exception as e:
        status["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    finally:
        status.update(running=False, step=None)


def loop(stop, minutes=60):
    while not stop.is_set():
        run(stop=stop, log=lambda m: print("[güncelleme]", m, flush=True))
        stop.wait(minutes * 60)


def start_background(minutes=60):
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop, minutes), daemon=True, name="kongre-sync").start()
    return stop


if __name__ == "__main__":
    db.init()
    run()
    sys.exit(1 if status["error"] else 0)
