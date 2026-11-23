# Yuzni tanish orqali sinf davomati — MVP

Texnik topshiriqning 1-bosqichi: RTSP kameradan har bir o'quvchini tanish va davomat olish.
Stack: Django + PostgreSQL + alohida tahlil jarayoni (worker) — OpenCV YuNet (yuz topish) va SFace (tanish), FFmpeg orqali RTSP, Docker Compose.

> **Docker'siz, kompyuter kamerasi bilan ishga tushirish:** [LOKAL_ISHGA_TUSHIRISH.md](LOKAL_ISHGA_TUSHIRISH.md).
> **Loyiha holati va bajarilgan ishlar:** [LOYIHA_HOLATI.md](LOYIHA_HOLATI.md).

## Arxitektura

```
IP kamera ──RTSP──▶ worker (FFmpeg dekodlash, YuNet + SFace; kadrlar faqat xotirada)
                        │  natija, holat, heartbeat
                        ▼
                    PostgreSQL ◀──── web (Django) ◀── Fetch API (2 s) ── brauzer
                        ▲                  ▲
                        └──── proxy (Caddy, HTTPS) ──┘
```

- `web` va `worker` bitta obrazdan, lekin alohida konteynerlarda; ular **PostgreSQL orqali** aloqa qiladi.
  Yagona istisno — administrator uchun **jonli ko'rish**. Kadrni bazaga yozish TZ ga zid bo'lgani uchun (kadr diskka tushmasligi kerak) worker uni
  ichki HTTP port (8765, faqat ichki tarmoq, maxfiy token) orqali faqat xotiradan beradi. Django ruxsatni tekshirib proksi qiladi.
  O'qituvchi ham sessiya oynasida o'z faol sessiyasi kamerasini ko'radi (kim tanilyapti, kim yo'q).
- Kamera markazi (`vision/hub.py`): har bir kameraga bitta ulanish — sessiya tahlili, jonli ko'rish va tekshiruv uni birga ishlatadi.
  Django sessiyani bazaga «Ochiq» deb yozadi → worker uni ko'rib (1 s davr bilan) kameraga ulanadi va natijani bazaga yozadi.
- Sessiya holatlari: `Ochiq → Ulanmoqda → Faol ⇄ Uzilgan → Yakunlangan → Tasdiqlangan`.
- Worker konteyneri `read_only` fayl tizimida ishlaydi: kadr va yuz kesimlari diskka tusha olmaydi.

## Ishga tushirish

```bash
cp .env.example .env
# .env ni to'ldiring:
#   DJANGO_SECRET_KEY, DB_PASSWORD, INITIAL_ADMIN_PASSWORD
#   FIELD_ENCRYPTION_KEYS  (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
#   SITE_ADDRESS / DJANGO_ALLOWED_HOSTS / DJANGO_CSRF_TRUSTED_ORIGINS — server IP yoki domeni
docker compose up -d --build
```

Brauzerda `https://<SITE_ADDRESS>` → `admin` / `INITIAL_ADMIN_PASSWORD`.
LAN uchun Caddy ichki sertifikat chiqaradi (brauzer bir marta ogohlantiradi; ishonchli bo'lishi uchun Caddy root CA ni o'quv kompyuterlariga o'rnating).

**Shifrlash kaliti** (`FIELD_ENCRYPTION_KEYS`) konteyner tashqarisida saqlanadi. Yo'qotilsa, andozalar va RTSP manzillarini ochib bo'lmaydi.
Kalitni almashtirish: yangi kalitni birinchi o'ringa, eskisini vergul bilan qoldiring.

### Kamerasiz sinov

```bash
docker compose --profile demo up -d rtsp
ffmpeg -re -stream_loop -1 -i sinf.mp4 -c copy -f rtsp rtsp://localhost:8554/sinf
docker compose exec web python manage.py seed_demo --rtsp rtsp://rtsp:8554/sinf
```

`seed_demo` xona, kamera, 7-A sinf, 10 ta o'quvchi va `oqituvchi` / `oqituvchi123` foydalanuvchisini yaratadi.

### Lokal ishlab chiqish (Docker'siz, SQLite)

```bash
python -m venv .venv && .venv/Scripts/pip install -r app/requirements.txt
# modellarni app/models/ ga yuklab oling (URL lar app/Dockerfile da)
cd app
set DJANGO_DEBUG=1 DJANGO_SECURE=0 FIELD_ENCRYPTION_KEYS=<kalit>
python manage.py migrate && python manage.py test
python manage.py runserver        # bir terminalda
python manage.py run_worker       # ikkinchi terminalda
```

Lokal sinovda kamera manzili o'rniga video fayl yo'lini yoki veb-kamera indeksini (`0`) yozish mumkin.

## Ish jarayoni

1. **Administrator** — «Boshqaruv» (`/boshqaruv/`, o'zimizning panel; Django admin ishlatilmaydi): xona, kamera (RTSP manzil shifrlanadi, interfeysda yashiriladi), sinf, o'quvchi (ID, F.I.Sh., sinf; CSV import), foydalanuvchi, biriktiruv, tanish parametrlari.
2. «Kameralar nazorati» → **jonli ko'rish va o'rnatish tekshiruvi** (F-15): kamera tasviri yuzlar ramkasi bilan (o'lcham, sifat, sessiyada — ism va ball), statistikani saqlash. O'quvchilarni barcha qatorlarga o'tqazib tekshiring.
3. «O'quvchilar bazasi»: **Sinflar** → **O'quvchilar** (familiya, ism, otasining ismi, sinf; ID avtomatik; CSV import) → **Yuz rasmlari** (sinf → o'quvchi → 3–5 ta rasm, fayldan yoki kameradan). Har bir rasmda bitta yuz, o'lcham, tiniqlik va bosh burilishi tekshiriladi; rasm faqat xotirada ishlanadi, bazaga faqat shifrlangan andoza yoziladi. Rozilik qayd etish talab qilinmaydi (buyurtmachi qarori, 20.11.2026).
4. **O'qituvchi** sinf va xonani tanlab sessiyani boshlaydi → davomat oynasi 2 s da yangilanadi: kamera holati, jonli hisob, «Tekshirish kerak: aniqlanmagan» va «Tekshirish kerak: noaniq (ehtimoliy nomzod)».
5. O'qituvchi «Keldi»/«Kelmadi» belgilaydi → «Sessiyani yakunlash» (tahlil to'xtaydi) → «Davomatni tasdiqlash» → hisobot va CSV.

## Moslikni tasdiqlash qoidasi

Barcha chegaralar «Boshqaruv → Tanish parametrlari» da sozlanadi (pilotda kalibrlanadi):

| Shart | Parametr | Boshlang'ich qiymat |
|---|---|---|
| Yuz sifati | min. yuz o'lchami / tiniqlik (Laplas dispersiyasi) / bosh burilishi | 40 px / 25 / 40° |
| Kosinus o'xshashlik ≥ T | `sim_threshold` | 0,363 (SFace) |
| Eng yaqin ikki o'quvchi farqi ≥ Δ | `margin_delta` | 0,05 |
| Vaqt oynasida ≥ N kadr | `confirm_frames`, `confirm_window_seconds` | 3 kadr / 10 s |
| Noaniq nomzod | `uncertain_threshold` | 0,30 |

Shartlardan biri bajarilmasa — noaniq moslik, davomat soniga qo'shilmaydi. Bir kadrda ikki yuz bitta o'quvchiga moslansa, faqat eng yuqori balli hisobga olinadi.
Faqat tanlangan sinfning yuz rasmi bor faol o'quvchilari andozalari bilan solishtiriladi; andozalar har 10 s da qayta yuklanadi (rasm o'chirilsa darhol chiqadi).

## Talablar bo'yicha bajarilish

| ID | Qayerda |
|---|---|
| F-01 | `core/models.py` (Room, Camera, SchoolClass, Student), `core/admin.py` |
| F-02 | `services.enroll_samples`, `vision/engine.py` — bitta yuz, o'lcham, xiralik, burilish chegaralari |
| F-03 | `services.start_session`; bazada `one_live_session_per_camera` qisman unikal cheklovi |
| F-04 | `vision/matcher.py`, `vision/worker.py` — faqat sinf andozalari, N kadrda tasdiq |
| F-05 | `templates/sessions/detail.html`, `static/js/live.js`, `/sessiyalar/<id>/holat/` |
| F-06 | `vision/capture.py` — 2, 4, 8 … 30 s cheksiz qayta urinish; natijalar saqlanadi |
| F-07 | `services.set_mark`, `end_session`; worker sessiya qatorini qulflab, faqat jonli sessiyaga yozadi |
| F-08 | `AttendanceRecord.source`: kamera / o'qituvchi / kamera + o'qituvchi |
| F-09 | `services.close_expired_sessions` (worker va veb chaqiradi) → «Tasdiqlanmagan (avtomatik yopilgan)» |
| F-10 | ⚠️ Rozilik olib tashlangan. `services.delete_templates` — rasm o'chirilsa o'quvchi tanishdan chiqadi va faqat qo'lda belgilanadi |
| F-11 | `AuditLog` — barcha qo'lda o'zgarishlar; tasdiqdan keyingilari alohida belgilanadi. Sessiya o'chirilganda (faqat administrator, «Sessiyalar» bo'limi) audit yozuvlari saqlanadi va o'chirishning o'zi qayd etiladi |
| F-12 | `services.session_report`, hisobot sahifasi va CSV (Excel uchun UTF-8 BOM, `;`) |
| F-13 | Django auth (login/parol, standart xesh), rollar: Administrator / O'qituvchi; biriktiruv har so'rovda tekshiriladi |
| F-14 | `VisibilityInterval` — o'quvchi hisoblangandan keyin ham kuzatiladi; hisobotda qamrov % |
| F-15 | «Kameralar nazorati» → jonli ko'rish va o'rnatish tekshiruvi (kadr saqlanmaydi) |
| F-16 | ⚠️ Rozilik interfeysdan olib tashlangan (`Consent` modeli eski yozuvlar uchun qoldirilgan) |
| F-17 | Sessiya → «Kuzatuv»: CSV shablon, yuklash va ko'rinish oraliqlari bilan solishtirish |

**Pilot metrikalari** («Pilot metrikalari» sahifasi): FP, FN, TP — sessiya boshlashda «Pilot: avval mustaqil yo'qlama» tanlansa,
o'qituvchi kamera natijasini ko'rmasdan oldin yo'qlama qiladi (natija server tomonda yashiriladi). Kechikish: kadr vaqti → brauzer
ko'rsatgan vaqt (brauzer serverga qaytaradi), 95-persentil. Uzilishdan tiklanish va kuzatish qamrovi ham hisoblanadi.

## Maxfiylik

- Jonli oqim, kadrlar, jonli yuz kesimlari va yuklangan namunalar diskka yozilmaydi (yuklash handleri faqat xotirada ishlaydi, 10 MB chegarasi).
- Istisno: andoza yaratilganda yuzning kichik kesimi (160×160 JPEG) **shifrlangan holda** bazaga yoziladi — administrator «Yuz rasmlari»da qaysi rasm biriktirilganini ko'rishi uchun. U faqat administratorga, keshlanmasdan beriladi va andoza bilan birga o'chadi.
- Andozalar va RTSP rekvizitlari Fernet bilan shifrlanadi; kalit env/secret da.
- Worker loglarida faqat ID lar; OpenCV/FFmpeg loglari o'chirilgan (RTSP manzil chiqmasligi uchun).
- Kamera faqat yopiq lokal tarmoqda bo'lishi kerak; compose RTSP portini tashqariga ochmaydi (`demo` profilidan tashqari).
- **Zaxira nusxalar:** andoza o'chirilganda u zaxira nusxalarda saqlanish muddati tugaguncha qoladi. Zaxira saqlash muddatini
  (masalan, 30 kun) belgilang va rozilik qaytarilganini hisobga olib, eski zaxiralarni muddatida yo'q qiling.
- Server O'zbekiston hududida joylashishi va rozilik shakli huquqshunos bilan tasdiqlanishi kerak (TZ 5-bo'lim).

## TZ ochiq savollari bo'yicha MVP da qabul qilingan vaqtinchalik qarorlar

Quyidagilar buyurtmachi bilan tasdiqlanguncha sozlanadigan standart qiymatlar:

- Tasdiqdan keyin davomatni **faqat administrator** o'zgartira oladi (audit bilan).
- Tasdiqlashda belgilanmagan kamera natijalari «Keldi» (kamera + o'qituvchi), hal qilinmagan «Tekshirish kerak» — «Kelmadi».
- Sessiya maksimal davomiyligi 120 daqiqa.
- Liveness (soxtalashtirishdan himoya) yo'q — qayd etilgan xavf; asosiy himoya — o'qituvchi tasdig'i.
- Kechikish holati, dars jadvali, tashqi tizimlarga eksport — MVP dan tashqari.

## Testlar

```bash
cd app && python manage.py test
```

Moslik mantiqi (T, Δ, N, sifat, oraliqlar), sessiya hayot sikli, bitta kamerada bitta sessiya, yopilgan sessiyaga yozish taqiqi,
ruxsatlar, rasm o'chirilganda tanishdan chiqish, o'quvchi F.I.Sh. va avtomatik ID, audit, hisobot sonlari, CSV, mustaqil yo'qlama va xotiradagi yuklash tekshiriladi.
