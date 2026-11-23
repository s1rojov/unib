# Loyiha holati — Yuzni tanish orqali sinf davomati (MVP)

**Sana:** 20.11.2026
**Bosqich:** 1-bosqich (MVP: davomat). Kod yozilgan va lokal sinovdan o'tgan. Pilot hali o'tkazilmagan.
**Asos:** «Texnik topshiriq: Yuzni tanish orqali sinf davomati (MVP)» (12 bet).
**Ishga tushirish:** `ishga_tushirish.bat` — bitta buyruq bilan, kompyuter kamerasi bilan; batafsil: [LOKAL_ISHGA_TUSHIRISH.md](LOKAL_ISHGA_TUSHIRISH.md). Docker bo'yicha: [README.md](README.md).

---

## 1. Qisqacha

| Yo'nalish | Holat |
|---|---|
| Funksional talablar F-01 … F-17 | ✅ Hammasi amalga oshirilgan |
| Lokal ishga tushirish (SQLite, kompyuter kamerasi) | ✅ Ishlaydi, tekshirilgan |
| Haqiqiy yuzni tanish (YuNet + SFace) | ✅ Video va kompyuter kamerasida tekshirilgan |
| Avtomatik testlar | ✅ 40 ta, hammasi o'tadi |
| Docker Compose (PostgreSQL + HTTPS) | ⚠️ Fayllar tayyor, lekin build qilib **sinalmagan** |
| Haqiqiy RTSP IP kamera, real sinf | ⏳ Sinalmagan (pilot vazifasi) |
| Chegaralarni kalibrlash (T, Δ, N, yuz o'lchami) | ⏳ Pilotda |

---

## 2. Arxitektura

```
Kamera (RTSP yoki kompyuter kamerasi "0")
   │  kadrlar faqat xotirada
   ▼
worker  (python manage.py run_worker)
   │  OpenCV YuNet — yuz va 5 ta nuqta; SFace — 128 o'lchamli andoza, kosinus o'xshashlik
   │  natija, holat, heartbeat
   ▼
Baza (lokal: SQLite / server: PostgreSQL)
   ▲
veb-ilova  (Django)  ◀── Fetch API, har 2 s ── brauzer (davomat oynasi)
```

- Veb-ilova va worker alohida jarayonlar. Ular bir-biri bilan **faqat baza orqali** aloqa qiladi, TZ 4-bo'limidagidek.
- Sessiya holatlari: `Ochiq → Ulanmoqda → Faol ⇄ Uzilgan → Yakunlangan → Tasdiqlangan`.
- Texnologiyalar: Python 3, Django 5.2, OpenCV (FFmpeg backend), NumPy, cryptography (Fernet).
  Serverda qo'shimcha: PostgreSQL 16, Gunicorn, Caddy (HTTPS), Docker Compose.

### Kod tuzilmasi

| Papka/fayl | Vazifasi |
|---|---|
| `app/core/models.py` | Ma'lumotlar modeli: xona, kamera, sinf, o'quvchi, foydalanuvchi va rol, biriktiruv, rozilik, yuz andozasi, sessiya, davomat yozuvi, ko'rinish oralig'i, kamera hodisasi, audit, kamera tekshiruvi, kuzatuvchi belgisi, tanish parametrlari |
| `app/core/services.py` | Biznes-mantiq: sessiya hayot sikli, belgilash, tasdiqlash, andoza yaratish va o'chirish, hisobotlar, pilot metrikalari |
| `app/core/views/` | Veb sahifalar va JSON API |
| `app/core/crypto.py` | Andoza va RTSP manzilni shifrlash |
| `app/vision/matcher.py` | Moslikni tasdiqlash qoidasi (sof mantiq, testlangan) |
| `app/vision/engine.py` | YuNet/SFace o'rami, sifat o'lchovlari |
| `app/vision/capture.py` | Kadr olish, qayta ulanish (2→4→8…30 s) |
| `app/vision/worker.py` | Tahlil jarayoni: sessiyalarni kuzatish, tanish, natijani yozish |
| `app/vision/hub.py` | Kamera markazi: bitta kameraga bitta ulanish (sessiya, jonli ko'rish, tekshiruv birga) |
| `app/vision/preview.py` | Jonli ko'rish: worker ichidagi HTTP server, kadr faqat xotiradan, yuz ramkalari |
| `app/core/views/crud.py` | O'zimizning boshqaruv paneli: ma'lumotnomalar uchun umumiy CRUD kontroller (model → forma → shablon) |
| `app/core/views/cameras.py` | Kameralar nazorati sahifasi va jonli kadr proksisi (ruxsat + audit) |
| `app/templates/`, `app/static/` | O'zbekcha interfeys (lotin), tashqi CDN'siz |
| `docker-compose.yml`, `app/Dockerfile`, `deploy/Caddyfile` | Server uchun joylashtirish |

---

## 3. Bajarilgan ishlar — talablar bo'yicha

| ID | Talab | Holat | Izoh |
|---|---|---|---|
| F-01 | Xona, kamera, sinf, o'quvchi boshqaruvi | ✅ | O'zimizning «Boshqaruv» paneli; tartib: Sinflar → O'quvchilar (familiya, ism, otasining ismi, sinf; ID avtomatik; CSV import) → Yuz rasmlari |
| F-02 | Sifatli namunalardan andoza | ✅ | Bitta yuz, min. o'lcham, xiralik, burilish tekshiriladi; fayl yuklash **yoki brauzerda kameradan suratga olish** |
| F-03 | Sessiya, kameraga avtomatik ulanish, 1 kamera = 1 faol sessiya | ✅ | Cheklov bazada (qisman unikal indeks) |
| F-04 | Faqat sinf andozalari, bir nechta kadrda tasdiq | ✅ | Qoida: sifat + T + Δ + N kadr / vaqt oynasi |
| F-05 | Davomat oynasi avtomatik yangilanadi | ✅ | 2 s; «Tekshirish kerak: aniqlanmagan» va «noaniq (ehtimoliy nomzod)» alohida |
| F-06 | Uzilish, qayta ulanish, natijalar saqlanadi | ✅ | 2, 4, 8 … 30 s, cheksiz; interfeysda banner |
| F-07 | Qo'lda «Keldi»/«Kelmadi», yopilgandan keyin kamera o'zgartira olmaydi | ✅ | Worker sessiyani qulflab tekshiradi |
| F-08 | Yozuv manbasi | ✅ | Kamera / O'qituvchi / Kamera + o'qituvchi |
| F-09 | Maksimal davomiylik, avtomatik yopish | ✅ | 120 daq (sozlanadi) → «Tasdiqlanmagan (avtomatik yopilgan)» |
| F-10 | Rozilik qaytarilsa andoza darhol o'chadi | ⚠️ | Buyurtmachi qarori bilan rozilik olib tashlandi. Rasm o'chirilsa o'quvchi jonli sessiyada ham ≤10 s ichida tanishdan chiqadi |
| F-11 | Audit jurnali | ✅ | Barcha qo'lda o'zgarishlar; tasdiqdan keyingilari alohida belgilanadi |
| F-12 | Hisobot 4 ta son bilan + CSV | ✅ | CSV Excel uchun (UTF-8 BOM, `;`) |
| F-13 | Login/parol, rollar | ✅ | Administrator / O'qituvchi; biriktiruv har so'rovda server tomonda tekshiriladi |
| F-14 | Ko'rinish xronologiyasi | ✅ | O'quvchi hisoblangandan keyin ham kuzatiladi; hisobotda qamrov % |
| F-15 | Kamera o'rnatish tekshiruvi | ✅ | «Kameralar nazorati»: jonli tasvir + yuz ramkalari (o'lcham/sifat), statistikani saqlash; kadr saqlanmaydi |
| F-16 | Rozilik ikki maqsad uchun alohida | ⚠️ | Olib tashlangan (buyurtmachi qarori, 20.11.2026) |
| F-17 | Kuzatuvchi shabloni | ✅ | CSV shablon → yuklash → ko'rinish oraliqlari bilan solishtirish |

### Nofunksional talablar

| Talab | Holat |
|---|---|
| Kadr, oqim, yuz kesimlari diskka yozilmaydi | ✅ Yuklangan rasmlar faqat xotirada (10 MB chegarasi); serverda worker faqat o'qish rejimida. ⚠️ Istisno: andoza yaratilganda yuzning 160×160 kesimi shifrlangan holda bazaga yoziladi (administrator biriktirilgan rasmni ko'rishi uchun), andoza bilan birga o'chadi |
| Andozalar shifrlangan, kalit tashqarida | ✅ Fernet; kalit `.env` da; kalitni almashtirish qo'llab-quvvatlanadi |
| RTSP rekvizitlari shifrlangan, interfeys va loglarda yashirin | ✅ |
| HTTPS | ✅ Serverda Caddy orqali. Lokalda HTTP (`127.0.0.1`) |
| Loglarda shaxsiy ma'lumot yo'q | ✅ Faqat ID |
| O'zbek tili (lotin), Asia/Tashkent | ✅ |
| Brauzer so'rov davri 2 s | ✅ |
| ≥ 5 kadr/s (CPU) | ✅ Kompyuterda ~7,5 kadr/s, kadr uchun ~50 ms |
| Bir sinfda 40 tagacha o'quvchi | ✅ Cheklov yo'q (40 kishilik yukda sinalmagan) |

### Pilot metrikalari (6-bo'lim)

- **«Mustaqil yo'qlama» rejimi:** o'qituvchi kamera natijasini ko'rmasdan oldin qo'lda yo'qlama qiladi. Kamera natijasi server tomonda yashiriladi.
- **«Pilot metrikalari» sahifasi:**
  - FP, FN, TP — sonda va foizda;
  - kechikish, 95-persentil: kadr vaqtidan to brauzerda ko'rsatilgan vaqtgacha (brauzer bu vaqtni serverga qaytaradi);
  - uzilishdan tiklanish vaqti;
  - kuzatish qamrovi.
- **Sessiya hisobotida:** «notanish yuzlar» hisobi.

---

## 4. Tekshiruv natijalari

| Sinov | Natija |
|---|---|
| Avtomatik testlar (`manage.py test`) | 40/40 o'tdi |
| Video fayl orqali to'liq zanjir: andoza → worker → davomat | 2 o'quvchi <1 s ichida tanildi (ball 0,91 / 0,93); kelmagan o'quvchi «Tekshirish kerak»da qoldi; yopilgandan keyin yozuvlar o'zgarmadi |
| Andoza rad etilishi | Kichik yuz, 2 ta yuzli rasm, yuzsiz rasm — to'g'ri xabar bilan rad etildi |
| Ishlamaydigan RTSP kamera | Holat «Uzilgan», kamera «offline», parol loglarga chiqmadi |
| Kameralar nazorati — jonli ko'rish (kompyuter kamerasi) | Birinchi kadr ~3 s da; sessiya va jonli ko'rish bitta kamera ulanishini birga ishlatdi (7,6 kadr/s); yuz ramkalari to'g'ri chizildi; tekshiruv saqlandi; ko'rish audit jurnaliga yozildi |
| O'zimizning boshqaruv paneli | Xona/kamera/sinf/o'quvchi/foydalanuvchi/biriktiruv CRUD, parametrlar, CSV import — testlar bilan; `/admin/` endi yo'q (404) |
| Kompyuter kamerasi + veb orqali sessiya | Ulanish ~2 s, «Faol», ~7,7 kadr/s, yuz har kadrda topildi. Andoza yuklanmagan edi, shu sababli tanish sinovi siz tomonda — [LOKAL_ISHGA_TUSHIRISH.md](LOKAL_ISHGA_TUSHIRISH.md), 4-bo'lim |

---

## 5. TZ ochiq savollari bo'yicha vaqtinchalik qarorlar

Buyurtmachi tasdiqlaguncha shunday ishlaydi; hammasi o'zgartiriladi:

- Tasdiqlangan davomatni **faqat administrator** o'zgartiradi (audit bilan).
- Tasdiqlashda belgilanmagan kamera natijasi «Keldi», hal qilinmagan «Tekshirish kerak» yozuvlari «Kelmadi» bo'ladi. O'qituvchi bu haqda oldindan ogohlantiriladi.
- Boshlang'ich chegaralar:
  - T = 0,363; Δ = 0,05; N = 3 kadr / 10 s; noaniq nomzod ≥ 0,30;
  - jonli tahlil: min. yuz 40 px, tiniqlik ≥ 25, burilish ≤ 40°;
  - andoza: min. yuz 80 px, tiniqlik ≥ 60, burilish ≤ 35°, 3–10 ta namuna;
  - sessiya ≤ 120 daqiqa.
- **Rozilik talab qilinmaydi** (buyurtmachi qarori, 20.11.2026): rasmi bor o'quvchi kamera bilan taniladi. Bu TZ 5-bo'limi (ota-ona roziligi) va F-10/F-16 dan chetlanish — huquqiy jihati buyurtmachi zimmasida. Ota-ona roziligi qog'ozda tashkiliy tarzda olinishi tavsiya etiladi.
- Liveness (telefondagi rasmga qarshi himoya) yo'q. Bu qayd etilgan xavf; asosiy himoya — o'qituvchi tasdig'i.

---

## 6. Ma'lum cheklovlar

- **Jonli ko'rish — arxitekturadagi yagona istisno.** TZ bo'yicha veb va worker faqat baza orqali aloqa qiladi.
  - Kadrni bazaga yozish TZ ning «kadr diskka yozilmaydi» talabiga zid bo'lardi.
  - Shuning uchun jonli kadr worker'ning ichki HTTP porti (8765) orqali faqat xotiradan beriladi. Port faqat lokal/ichki tarmoqda ochiladi va maxfiy token bilan himoyalangan.
  - Administrator barcha kameralarni ko'radi. O'qituvchi faqat o'z **faol sessiyasi** kamerasini sessiya oynasida ko'radi (ramkalarda tanilgan o'quvchi ismi); sessiya yakunlangach va «mustaqil yo'qlama» tugaguncha ko'rsatilmaydi. Har bir ko'rish audit jurnaliga yoziladi.
  - Kerak bo'lmasa, `CAMERA_PREVIEW_ENABLED=0` bilan o'chiriladi.
  - Bu buyurtmachi bilan kelishilishi kerak, chunki administrator va o'qituvchi sinfni jonli kuzata oladi.

- **Docker build va PostgreSQL** bilan ishlash hali sinalmagan. Kod PostgreSQL uchun yozilgan, testlar esa SQLite'da o'tgan.
- **Kamera bandligi:** kompyuter kamerasi bir vaqtda bitta dasturda ishlaydi. Sessiya ochiq paytda brauzer orqali andoza olib bo'lmaydi, kamera tekshiruvini ham o'tkazib bo'lmaydi.
- **Bosh burilishi baholanishi taxminiy** (5 ta nuqtadan hisoblanadi) va pilotda kalibrlanishi kerak.
- **Zaxira nusxalardan andozani o'chirish** — tashkiliy masala. Zaxira saqlash muddati belgilanishi kerak.
- **Lokal rejimda HTTPS yo'q.** Bu faqat `127.0.0.1` uchun; tarmoqqa ochishda Docker/Caddy varianti ishlatiladi.

---

## 7. O'zgarishlar tarixi

| Sana | O'zgarish |
|---|---|
| 20.11.2026 | MVP: F-01…F-17, testlar, Docker konfiguratsiyasi |
| 20.11.2026 | Lokal ishga tushirish: kompyuter kamerasi, brauzerda kameradan andoza olish, `ishga_tushirish.bat` (bitta buyruq) |
| 20.11.2026 | Django admin olib tashlandi → o'zimizning «Boshqaruv» paneli (CRUD, parametrlar, CSV import). «Kameralar nazorati»: jonli tasvir, yuz ramkalari, kamera markazi (bitta ulanish) |
| 20.11.2026 | Interfeys CRM uslubiga o'tkazildi: chap yon panel (bo'limlar va ikonkalar), yuqori panel (sahifa yo'li, soat, foydalanuvchi), KPI kartalar, sarlavhali jadval kartalari, ikki ustunli kirish sahifasi, mobil menyu. Bosh sahifaga bugungi ko'rsatkichlar qo'shildi |
| 20.11.2026 | O'quvchi kiritish soddalashtirildi: rozilik olib tashlandi; tartib Sinflar → O'quvchilar (familiya, ism, otasining ismi, sinf; ID avtomatik; «Saqlash va yana qo'shish») → alohida «Yuz rasmlari» sahifasi (sinf → o'quvchi → rasm, «keyingi o'quvchi» tugmasi). Migratsiya `0002`: eski F.I.Sh. avtomatik familiya/ismga ajratiladi |
| 20.11.2026 | «Yuz rasmlari»: biriktirilgan rasmlar galereyasi (yuzning shifrlangan 160×160 kesimi), yangi qo'shilganlar belgilanadi, o'quvchilar ro'yxatida rasm-avatar. Migratsiya `0003` |
| 20.11.2026 | Sessiya oynasida o'qituvchi uchun jonli kamera: yuz ramkalari (tanildi / noaniq / notanish / sifat past) va ismlar; faqat o'z faol sessiyasi, pilot rejimida yashirin |
| 20.11.2026 | Chiroyli tanlash ro'yxatlari (qidiruv, klaviatura). Administrator uchun «Sessiyalar» bo'limi: filtrlar (holat, sinf, o'qituvchi, sana), bir nechtasini tanlab o'chirish, tasdiqlash sahifasi; davom etayotgan sessiya o'chirilmaydi; o'chirish audit jurnaliga yoziladi, eski audit yozuvlari saqlanadi |

## 8. Keyingi qadamlar

1. **Siz tomonda:**
   - lokal ishga tushirish va o'zingizni andoza qilib tanitish;
   - bir nechta odam bilan sinash;
   - chegaralarni his qilib ko'rish.
2. **Docker Desktop'ni yoqib** `docker compose up -d --build` ni sinash (PostgreSQL + HTTPS).
3. **Pilot uchun tayyorgarlik:**
   - 1080p+ RTSP kamera va uning joylashuvi;
   - «Kameralar nazorati» → jonli ko'rish orqali barcha qatorlarni tekshirish;
   - ota-ona rozilik shakli (huquqshunos bilan);
   - server joyi va apparat tavsifi.
4. **Pilot:** kamida 2 hafta, «mustaqil yo'qlama» rejimida. Shu davrda FP/FN/kechikish chegaralari tasdiqlanadi, so'ng T, Δ, N kalibrlanadi.
5. **2-bosqichga o'tish darvozasi:** kuzatish qamrovi (F-14) va kuzatuvchi ma'lumotlari (F-17) bo'yicha qaror qabul qilinadi.
