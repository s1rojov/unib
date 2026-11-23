"""Loyihani bitta buyruq bilan lokal ishga tushirish (Docker'siz, kompyuter kamerasi bilan).

    python run_local.py          yoki  ishga_tushirish.bat  (ikki marta bosish)

Kerak bo'lsa avtomatik bajaradi:
  1) .venv yaratadi va kutubxonalarni o'rnatadi
  2) yuzni tanish modellarini yuklab oladi
  3) app/.env ni tasodifiy kalitlar bilan yaratadi
  4) bazani tayyorlaydi (birinchi marta — namunaviy ma'lumotlar bilan)
  5) veb-server va worker'ni birga ishga tushiradi, brauzerni ochadi
To'xtatish: Ctrl+C (ikkala jarayon ham to'xtaydi).
"""
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", "8000"))
URL = f"http://{HOST}:{PORT}/"

MODELS = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")


def say(msg):
    print(f"\n==> {msg}", flush=True)


def run(args, **kw):
    subprocess.run(args, check=True, env=ENV, **kw)


def ensure_venv():
    if VENV_PY.exists():
        try:
            run([str(VENV_PY), "-c", "import django, cv2, cryptography, whitenoise"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except subprocess.CalledProcessError:
            pass
    else:
        say("Python muhiti yaratilmoqda (.venv)")
        run([sys.executable, "-m", "venv", str(VENV)])
    say("Kutubxonalar oʻrnatilmoqda (bir necha daqiqa)")
    run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(APP / "requirements.txt")])


def ensure_models():
    d = APP / "models"
    d.mkdir(exist_ok=True)
    for name, url in MODELS.items():
        f = d / name
        if f.exists() and f.stat().st_size > 100_000:
            continue
        say(f"Model yuklab olinmoqda: {name}")
        tmp = f.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(f)


def ensure_env():
    env_file = APP / ".env"
    if env_file.exists():
        return
    say("Sozlamalar fayli yaratilmoqda: app/.env")
    key = subprocess.check_output(
        [str(VENV_PY), "-c", "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"],
        text=True).strip()
    env_file.write_text(
        "# Lokal ishga tushirish sozlamalari. Bu fayl gitga qo'shilmaydi.\n"
        "DJANGO_DEBUG=1\nDJANGO_SECURE=0\n"
        f"DJANGO_SECRET_KEY={secrets.token_urlsafe(48)}\n"
        "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n"
        "# Shifrlash kaliti: YO'QOTMANG — yo'qolsa andozalarni ochib bo'lmaydi\n"
        f"FIELD_ENCRYPTION_KEYS={key}\n"
        "INITIAL_ADMIN_USERNAME=admin\nINITIAL_ADMIN_PASSWORD=Admin12345!\n"
        "WORKER_THREADS=1\n",
        encoding="utf-8",
    )


def manage(*args, **kw):
    run([str(VENV_PY), "manage.py", *args], cwd=APP, **kw)


def prepare_db():
    first_run = not (APP / "dev.sqlite3").exists()
    say("Baza tayyorlanmoqda")
    manage("migrate", "--noinput", stdout=subprocess.DEVNULL)
    manage("ensure_admin")
    if first_run:
        manage("seed_demo", "--students", "5")


def port_busy():
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def wait_ready(timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if port_busy():
            return True
        time.sleep(0.5)
    return False


def stop(procs):
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows konsoli uchun
        except Exception:
            pass
    os.chdir(ROOT)
    ensure_venv()
    ensure_models()
    ensure_env()
    prepare_db()
    if port_busy():
        sys.exit(f"\n{PORT}-port band. Avvalgi nusxa ishlayotgan boʻlishi mumkin — uni yoping "
                 f"yoki boshqa port bilan ishga tushiring:  set PORT=8001 && python run_local.py")

    say("Veb-server va kamera tahlili (worker) ishga tushirilmoqda")
    web = subprocess.Popen([str(VENV_PY), "manage.py", "runserver", f"{HOST}:{PORT}", "--noreload"], cwd=APP, env=ENV)
    worker = subprocess.Popen([str(VENV_PY), "manage.py", "run_worker"], cwd=APP, env=ENV)
    procs = [web, worker]
    try:
        if wait_ready():
            print(
                "\n" + "=" * 60 +
                f"\n  Tizim ishga tushdi:  {URL}"
                "\n  Administrator:  admin / Admin12345!"
                "\n  Oʻqituvchi:     oqituvchi / oqituvchi123"
                "\n  Toʻxtatish:     Ctrl+C"
                "\n" + "=" * 60 + "\n", flush=True)
            webbrowser.open(URL)
        while True:
            for p, name in ((web, "Veb-server"), (worker, "Worker")):
                if p.poll() is not None:
                    print(f"\n{name} toʻxtadi (kod {p.returncode}). Hammasi toʻxtatilmoqda.")
                    return
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nToʻxtatilmoqda…")
    finally:
        stop(procs)
        print("Toʻxtatildi.")


if __name__ == "__main__":
    main()
