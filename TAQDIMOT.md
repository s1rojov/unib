# Yuzni tanish orqali sinf davomati — loyiha taqdimoti

> **Kim uchun:** loyihaga yangi qo'shilgan odam (administrator, o'qituvchi yoki dasturchi).
> **Holat sanasi:** 24.11.2026 (kod va testlar shu kuni tekshirilgan).
> **Qisqa javob «nimadan boshlayman?»:** `ishga_tushirish.bat` ni ikki marta bosing → `admin` bilan kiring → o'zingizni o'quvchi qilib yuz rasmini biriktiring → `oqituvchi` bilan sessiya oching. Batafsil — [5-bo'lim](#5-ishni-nimadan-boshlash-kerak).

---

## Mundarija

1. [Loyiha nima qiladi](#1-loyiha-nima-qiladi)
2. [Hozirgi holat](#2-hozirgi-holat)
3. [Qanday ishlaydi (arxitektura)](#3-qanday-ishlaydi-arxitektura)
4. [Rollar va menyu xaritasi](#4-rollar-va-menyu-xaritasi)
5. [Ishni nimadan boshlash kerak](#5-ishni-nimadan-boshlash-kerak)
6. [Administrator: tizimni noldan sozlash](#6-administrator-tizimni-noldan-sozlash)
7. [O'qituvchi: bitta dars davomati](#7-oqituvchi-bitta-dars-davomati)
8. [Tanish qoidasi va parametrlar](#8-tanish-qoidasi-va-parametrlar)
9. [Maxfiylik va xavfsizlik](#9-maxfiylik-va-xavfsizlik)
10. [Dasturchi uchun](#10-dasturchi-uchun)
11. [Muammolar va yechimlar](#11-muammolar-va-yechimlar)
12. [Tahlilda topilgan kamchiliklar](#12-tahlilda-topilgan-kamchiliklar)
13. [Keyingi qadamlar (yo'l xaritasi)](#13-keyingi-qadamlar-yol-xaritasi)
14. [Atamalar lug'ati](#14-atamalar-lugati)

---

## 1. Loyiha nima qiladi

Sinfdagi kamera dars davomida o'quvchilarning yuzini taniydi va davomatni o'zi to'ldiradi. O'qituvchi faqat kamera ishonch hosil qila olmagan o'quvchilarni qo'lda belgilaydi va oxirida davomatni tasdiqlaydi.

- **Asos:** «Texnik topshiriq: Yuzni tanish orqali sinf davomati (MVP)» — loyiha papkasidagi PDF.
- **Bosqich:** 1-bosqich (MVP) — faqat davomat. 2-bosqich (xatti-harakat tahlili) hali boshlanmagan, lekin unga ma'lumot yig'ish vositalari (ko'rinish oraliqlari, kuzatuvchi belgilari) tayyor.
- **Asosiy g'oya:** kamera **yordamchi**, yakuniy qaror — o'qituvchida. Kamera faqat ishonchli bo'lganda «Keldi» deydi, qolganlarini «Tekshirish kerak» ga qo'yadi.

---

## 2. Hozirgi holat

| Yo'nalish | Holat | Izoh |
|---|---|---|
| Funksional talablar F-01 … F-17 | ✅ Bajarilgan | F-10, F-16 (rozilik) buyurtmachi qarori bilan olib tashlangan |
| Lokal ishga tushirish (Windows, SQLite, kompyuter kamerasi) | ✅ Ishlaydi | `ishga_tushirish.bat` — bitta buyruq |
| Yuzni tanish (YuNet + SFace) | ✅ Ishlaydi | Video va noutbuk kamerasida sinalgan, ~7,5 kadr/s |
| Avtomatik testlar | ✅ **40/40 o'tadi** | 24.11.2026 da qayta tekshirildi |
| Shifrlash, audit, hisobot, CSV | ✅ Bajarilgan | |
| Docker Compose (PostgreSQL + HTTPS) | ⚠️ Fayllar tayyor, **sinalmagan** | Birinchi navbatdagi texnik vazifa |
| Haqiqiy RTSP IP kamera, real sinf | ⏳ Sinalmagan | Pilot vazifasi |
| Chegaralarni kalibrlash (T, Δ, N) | ⏳ Pilotda | Hozir standart qiymatlar |
| Liveness (telefondagi rasmga qarshi himoya) | ❌ Yo'q | Qayd etilgan xavf, himoya — o'qituvchi tasdig'i |

**Bir gapda:** dastur to'liq yozilgan va bitta kompyuterda ishlaydi; endi uni **serverga chiqarish** (Docker) va **haqiqiy sinfda pilot** qilish kerak.

### Hozirgi kompyuterdagi holat (D:\Projects\unib)

- `.venv` (Python 3.14), modellar (`app\models\*.onnx`), `app\.env` va baza (`app\dev.sqlite3`) **allaqachon bor** — o'rnatish shart emas, darhol ishga tushirish mumkin.
- Git: bitta commit (`first commit`), `master` tarmog'i.

---

## 3. Qanday ishlaydi (arxitektura)

```
 Kamera (RTSP IP-kamera yoki kompyuter kamerasi "0")
    │  kadrlar FAQAT xotirada, diskka yozilmaydi
    ▼
 ┌───────────────────────────────┐
 │ WORKER  (manage.py run_worker)│  YuNet — yuzni topadi
 │  kamera markazi (hub)         │  SFace — 128 o'lchamli "yuz izi" (andoza)
 │  sessiya tahlilchilari        │  kosinus o'xshashlik → kim ekanini aniqlaydi
 └──────────────┬────────────────┘
                │ natija, holat, heartbeat (har 1 s)
                ▼
         ┌─────────────┐
         │    BAZA     │   lokal: SQLite  ·  server: PostgreSQL 16
         └──────▲──────┘
                │
 ┌──────────────┴────────────────┐
 │ VEB-ILOVA (Django)            │ ◀── brauzer har 2 s da so'raydi (Fetch API)
 └───────────────────────────────┘
        serverda oldida: Caddy (HTTPS)
```

**Muhim tamoyillar:**

1. **Ikki alohida jarayon.** Veb-ilova va worker bir-biri bilan **faqat baza orqali** gaplashadi. O'qituvchi sessiya ochsa, Django bazaga «Ochiq» yozadi; worker buni 1 soniyada ko'rib kameraga ulanadi.
2. **Yagona istisno — jonli ko'rish.** Kadrni bazaga yozib bo'lmaydi (maxfiylik), shuning uchun worker ichki port **8765** orqali kadrni xotiradan beradi; Django ruxsatni tekshirib uzatadi. Kerak bo'lmasa `CAMERA_PREVIEW_ENABLED=0`.
3. **Bitta kamera — bitta ulanish.** Sessiya, jonli ko'rish va o'rnatish tekshiruvi bitta kamera oqimini birga ishlatadi (`vision/hub.py`).
4. **Bitta kamerada bir vaqtda bitta faol sessiya** — bu bazada cheklov sifatida yozilgan.

### Sessiya hayot sikli

```
Ochiq → Ulanmoqda → Faol ⇄ Uzilgan → Yakunlangan → Tasdiqlangan
                                         │
                                         └─ 120 daq. o'tsa: «Tasdiqlanmagan (avtomatik yopilgan)»
```

- **Uzilgan:** kamera uzilsa worker 2 → 4 → 8 … 30 s oraliq bilan cheksiz qayta ulanadi; to'plangan natijalar yo'qolmaydi.
- **Yakunlangan:** kamera tahlili to'xtaydi, endi kamera hech narsani o'zgartira olmaydi.
- **Tasdiqlangan:** belgilanmagan yozuvlar yakunlanadi; keyingi o'zgarishni faqat administrator qila oladi (audit bilan).

### Texnologiyalar

| Qatlam | Texnologiya |
|---|---|
| Backend | Python 3, Django 5.2 |
| Kompyuter ko'rishi | OpenCV (FFmpeg backend), YuNet 2023mar, SFace 2021dec, NumPy |
| Shifrlash | `cryptography` (Fernet, kalit almashtirish qo'llab-quvvatlanadi) |
| Baza | SQLite (lokal, WAL rejimi) / PostgreSQL 16 (server) |
| Server | Gunicorn, WhiteNoise, Caddy 2.8 (HTTPS), Docker Compose |
| Frontend | Django shablonlari, toza JS (kutubxonasiz), o'zbek tili (lotin) |

---

## 4. Rollar va menyu xaritasi

Tizimda **ikki rol** bor. Rol foydalanuvchini yaratishda tanlanadi.

| | Administrator | O'qituvchi |
|---|---|---|
| Ma'lumotnomalar (xona, kamera, sinf, o'quvchi, foydalanuvchi) | ✅ | ❌ |
| Yuz rasmlarini biriktirish | ✅ | ❌ |
| Sessiya **boshlash** | ❌ (faqat o'qituvchi) | ✅ faqat o'ziga biriktirilgan sinf/xona |
| Sessiyani ko'rish | barchasi | faqat o'ziniki |
| Tasdiqlangan davomatni o'zgartirish | ✅ (auditga yoziladi) | ❌ |
| Jonli kamera | barcha kameralar | faqat o'z faol sessiyasi kamerasi |
| Sessiyalarni o'chirish, audit, pilot metrikalari, parametrlar | ✅ | ❌ |

> ⚠️ Administrator sessiya **ocha olmaydi** — bu ataylab qilingan. Sinab ko'rish uchun alohida o'qituvchi hisobi kerak.

### Administrator menyusi (chap panel)

| Bo'lim | Sahifa | Manzil | Nima uchun |
|---|---|---|---|
| Asosiy | Bosh sahifa | `/` | Bugungi ko'rsatkichlar, faol sessiyalar |
| Sessiyalar | Barcha sessiyalar / Faol sessiyalar | `/boshqaruv/sessiyalar/` | Filtrlar, ko'rish, o'chirish |
| O'quvchilar bazasi | Sinflar | `/boshqaruv/sinflar/` | Sinf qo'shish |
| | O'quvchilar | `/boshqaruv/oquvchilar/` | Qo'shish, tahrirlash, CSV import |
| | Yuz rasmlari | `/boshqaruv/rasmlar/` | Sinf → o'quvchi → 3–5 rasm |
| Nazorat | Kameralar nazorati | `/boshqaruv/kameralar/` | Holat, jonli ko'rish, o'rnatish tekshiruvi, kamera qo'shish |
| Ma'lumotnomalar | Xonalar, Foydalanuvchilar, Biriktiruvlar | `/boshqaruv/...` | Asosiy sozlash |
| Tahlil va sozlamalar | Pilot metrikalari, Audit jurnali, Tanish parametrlari | `/boshqaruv/pilot/`, `/audit/`, `/parametrlar/` | Sifat nazorati va kalibrlash |

### O'qituvchi menyusi

Faqat **Bosh sahifa** (sessiyani boshlash tugmasi) va **Sessiyalar** (o'z sessiyalari, hisobotlar).

> Django'ning standart `/admin/` paneli **yo'q** — barcha boshqaruv o'zimizning «Boshqaruv» panelida.

---

## 5. Ishni nimadan boshlash kerak

Kim ekaningizga qarab yo'lni tanlang:

| Siz kimsiz | Boshlang | Vaqt |
|---|---|---|
| Tizim bilan tanishmoqchi bo'lgan har kim | **5.1 — Birinchi 15 daqiqa** | 15 daq |
| Maktab administratori (haqiqiy sinfni sozlash) | 5.1, keyin [6-bo'lim](#6-administrator-tizimni-noldan-sozlash) | 1–2 soat |
| O'qituvchi | [7-bo'lim](#7-oqituvchi-bitta-dars-davomati) | 10 daq |
| Dasturchi | 5.1, keyin [10-bo'lim](#10-dasturchi-uchun) va [12-bo'lim](#12-tahlilda-topilgan-kamchiliklar) | 1 kun |

### 5.1. Birinchi 15 daqiqa (bitta kompyuterda, noutbuk kamerasi bilan)

**Talablar:** Windows, Python 3.12+ (`python` buyrug'i ishlashi kerak), internet (faqat birinchi marta — kutubxonalar va modellar uchun), veb-kamera, Chrome yoki Edge.

**1-qadam. Ishga tushirish.**
`D:\Projects\unib\ishga_tushirish.bat` ni ikki marta bosing. U o'zi:
1. `.venv` yaratadi va kutubxonalarni o'rnatadi;
2. yuzni tanish modellarini yuklab oladi;
3. tasodifiy kalitlar bilan `app\.env` yaratadi;
4. bazani tayyorlaydi, birinchi marta namunaviy ma'lumot qo'shadi;
5. veb-server va worker'ni birga ishga tushirib, brauzerda **http://127.0.0.1:8000** ni ochadi.

Konsol oynasini **yopmang** — u dastur o'zi. To'xtatish: `Ctrl+C`.

**2-qadam. Kirish ma'lumotlari** (namunaviy):

| Rol | Login | Parol |
|---|---|---|
| Administrator | `admin` | `Admin12345!` |
| O'qituvchi | `oqituvchi` | `oqituvchi123` |

Namunaviy ma'lumot: `101-xona`, «Sinf kamerasi» (= kompyuter kamerasi `0`), `7-A (2026-2027)` sinfi va 5 ta o'quvchi («Oʻquvchi 01» … «Oʻquvchi 05»).

**3-qadam. O'zingizni o'quvchi qiling** (`admin` bilan):
1. **O'quvchilar** → «Oʻquvchi 01» → «Tahrirlash» → familiya va ismingizni yozing → Saqlash.
2. **Yuz rasmlari** → chapda o'zingizni tanlang → «Kameradan suratga olish» → «Kamerani yoqish».
3. Kameraga qarab **3–5 ta surat** oling: to'g'riga, biroz chapga, biroz o'ngga → «Biriktirish».
4. Holat **«tayyor»** bo'lishi kerak. «xira», «yuz kichik», «bosh burilgan» chiqsa — yorug'roq joyda, yaqinroq turib qayta oling.

**4-qadam. Dars o'tkazing** (chiqing va `oqituvchi` bilan kiring):
1. **Bosh sahifa** → «Sessiyani boshlash» → 7-A / 101-xona → Boshlash.
2. Kameraga qarang: 1–3 soniyada siz **«Keldi — Kamera»** bo'lasiz.
3. Qolgan 4 o'quvchi «Tekshirish kerak» da — ularni «Keldi»/«Kelmadi» bilan belgilang.
4. «Sessiyani yakunlash» → «Davomatni tasdiqlash» → **Hisobot** → «CSV yuklab olish».

> ⚠️ Kamera bir vaqtda **bitta dasturda** ishlaydi. Rasm olayotganda sessiya ochiq bo'lmasin va aksincha. Zoom/Teams ham kamerani band qiladi.

Shu 4 qadamdan keyin siz tizimning butun zanjirini ko'rgan bo'lasiz.

---

## 6. Administrator: tizimni noldan sozlash

Haqiqiy maktab uchun quyidagi **tartibda** bajaring (har bir keyingi qadam oldingisiga bog'liq):

```
1. Xonalar ─▶ 2. Kameralar ─▶ 3. Kamera tekshiruvi
                                     │
4. Sinflar ─▶ 5. O'quvchilar ─▶ 6. Yuz rasmlari
                                     │
7. O'qituvchilar (foydalanuvchi) ─▶ 8. Biriktiruvlar ─▶ 9. Birinchi sessiya
```

| # | Qayerda | Nima qilish | Diqqat |
|---|---|---|---|
| 0 | Foydalanuvchilar | `admin` parolini almashtiring | Standart parol hamma hujjatda yozilgan |
| 1 | Ma'lumotnomalar → **Xonalar** | Har bir sinf xonasini qo'shing (`101-xona`) | |
| 2 | Nazorat → **Kameralar nazorati** → qo'shish | Xona, nom, RTSP manzil: `rtsp://login:parol@192.168.1.50:554/stream1`. Lokal sinovda `0`, `1` (kompyuter kamerasi) yoki video fayl yo'li | Manzil shifrlanadi va interfeysda yashiriladi. Xonada **faol** kamera bo'lmasa sessiya ochilmaydi |
| 3 | Kameralar nazorati → **▶ Jonli ko'rish** | Bolalarni barcha qatorlarga o'tqazing, har bir yuz ramkasini ko'ring → «Tekshiruvni saqlash» | Ramka ranglari: 🟩 tanildi, 🟨 noaniq, 🟥 notanish, ⬜ yuz kichik/sifat past. Orqa qatordagi yuzlar ≥ 40 px bo'lishi kerak |
| 4 | O'quvchilar bazasi → **Sinflar** | Nomi (`7-A`) va o'quv yili (`2026-2027`) | Nom + yil juftligi takrorlanmasligi kerak |
| 5 | **O'quvchilar** | Qo'lda (familiya, ism, otasining ismi, sinf; ID avtomatik `S00001`…) yoki **CSV import** | CSV: har qatorda `Familiya;Ism;Otasining ismi` yoki bitta katakda «Familiya Ism». Sarlavha qatori o'tkazib yuboriladi, sinfda bor ism qayta qo'shilmaydi |
| 6 | **Yuz rasmlari** | Sinf → o'quvchi → 3–5 rasm (fayldan yoki kameradan) → «keyingi o'quvchi» | Har rasmda **bitta** yuz, ≥ 80 px, tiniq, bosh burilishi ≤ 35°. Rasm faqat xotirada ishlanadi; bazaga shifrlangan andoza va 160×160 kichik kesim yoziladi. Rasmi yo'q o'quvchi faqat qo'lda belgilanadi |
| 7 | Ma'lumotnomalar → **Foydalanuvchilar** | O'qituvchilarni yarating, rol: «Oʻqituvchi» | Parol ≥ 8 belgi, oddiy bo'lmasin. Ishdan ketganni o'chirmang — **nofaol** qiling |
| 8 | **Biriktiruvlar** | O'qituvchi → sinf → xona | Biriktiruvsiz o'qituvchi sessiya ocha olmaydi |
| 9 | O'qituvchi bilan sessiya | [7-bo'lim](#7-oqituvchi-bitta-dars-davomati) | Pilot uchun «mustaqil yo'qlama» belgisini qo'ying |

**Muntazam vazifalar:**
- **Audit jurnali** — kim, qachon, nimani o'zgartirgan (tasdiqdan keyingi o'zgarishlar alohida belgilanadi).
- **Pilot metrikalari** — FP/FN/TP, kechikish (95-persentil), uzilishdan tiklanish, kuzatish qamrovi.
- **Tanish parametrlari** — pilot natijasiga qarab chegaralarni o'zgartirish ([8-bo'lim](#8-tanish-qoidasi-va-parametrlar)).
- **Barcha sessiyalar** — eski/xato sessiyalarni o'chirish (davom etayotgani o'chirilmaydi, audit saqlanadi).

---

## 7. O'qituvchi: bitta dars davomati

1. **Kirish** → Bosh sahifa → **«Sessiyani boshlash»** → sinf va xonani tanlang.
   - *Pilot davrida:* «Pilot: avval mustaqil yoʻqlama» ni belgilang — avval kamerani ko'rmasdan o'zingiz yo'qlama qilasiz, keyin kamera natijasi ochiladi.
2. **Davomat oynasi** har 2 soniyada o'zi yangilanadi:
   - yuqorida — kamera holati (Ulanmoqda / Faol / Uzilgan) va jonli kamera tasviri (tanilganlar ismi bilan);
   - **«Keldi»** — kamera ishonch bilan tanigan o'quvchilar;
   - **«Tekshirish kerak: aniqlanmagan»** — kamera umuman ko'rmagan;
   - **«Tekshirish kerak: noaniq (ehtimoliy nomzod)»** — o'xshash, lekin ishonch yetarli emas.
3. «Tekshirish kerak» dagilarni **«Keldi»/«Kelmadi»** bilan belgilang. Kamera xato qilgan bo'lsa, «Keldi» ni ham «Kelmadi» ga o'zgartirish mumkin.
4. **«Sessiyani yakunlash»** — kamera tahlili to'xtaydi.
5. **«Davomatni tasdiqlash»** — belgilanmaganlar avtomatik: kamera tanigan → «Keldi», qolganlari → «Kelmadi». Oldindan ogohlantiriladi.
6. **Hisobot** → 4 ta asosiy son (jami / keldi / kelmadi / tekshirilgan) va **CSV** (Excel'da to'g'ri ochiladi).

Sessiya 120 daqiqadan oshsa avtomatik yopiladi — «Tasdiqlanmagan (avtomatik yopilgan)»; uni baribir tasdiqlash kerak.

**Yozuv manbasi** hisobotda ko'rinadi: *Kamera* / *O'qituvchi* / *Kamera + o'qituvchi*.

---

## 8. Tanish qoidasi va parametrlar

Kamera o'quvchini **«Keldi»** deb hisoblashi uchun **barcha** shartlar bajarilishi kerak:

| Shart | Parametr | Standart |
|---|---|---|
| Yuz sifati yaxshi | min. o'lcham / tiniqlik / bosh burilishi | 40 px / 25 / 40° |
| O'xshashlik yetarli | `T` — kosinus o'xshashlik chegarasi | 0,363 |
| Ikkinchi nomzoddan aniq ustun | `Δ` — eng yaqin ikki o'quvchi farqi | 0,05 |
| Bir necha kadrda takrorlangan | `N` kadr / vaqt oynasi | 3 kadr / 10 s |

- Shartlardan biri bajarilmasa, lekin o'xshashlik ≥ 0,30 bo'lsa — **«Noaniq»** (davomatga qo'shilmaydi).
- Bir kadrda ikki yuz bitta o'quvchiga mos kelsa — faqat eng yuqori ballisi hisobga olinadi.
- Faqat **tanlangan sinf** o'quvchilari bilan solishtiriladi; andozalar har 10 s da qayta yuklanadi (rasm o'chirilsa o'quvchi ≤ 10 s ichida tanishdan chiqadi).

**Qanday sozlash kerak** (Tahlil va sozlamalar → Tanish parametrlari):

| Muammo | Nima qilish |
|---|---|
| Ko'p o'quvchi «Noaniq» yoki tanilmayapti | Avval 1–2 ta qo'shimcha rasm (boshqa burchak/yorug'lik). Keyin `T` ni biroz pasaytiring (0,33) |
| Kamera boshqa o'quvchini «Keldi» qilyapti (FP) | `T` ni oshiring, `Δ` ni oshiring, `N` ni 4–5 ga ko'taring |
| Orqa qatorlar «sifat past» | Kamera joyini/zoomni o'zgartiring; zarurat bo'lsa min. yuz o'lchamini pasaytiring |

> Qiymatlarni **pilot ma'lumotiga** (Pilot metrikalari sahifasidagi FP/FN) qarab o'zgartiring, taxmin bilan emas.

---

## 9. Maxfiylik va xavfsizlik

- **Kadrlar, video oqim, yuklangan rasmlar diskka yozilmaydi** — faqat xotirada. Serverda worker konteyneri faqat o'qish rejimida.
  *Istisno:* andoza yaratilganda yuzning 160×160 kesimi **shifrlangan** holda bazaga yoziladi (administrator ko'rishi uchun), andoza bilan birga o'chadi.
- **Andozalar va RTSP manzillar** Fernet bilan shifrlanadi. Kalit — `.env` dagi `FIELD_ENCRYPTION_KEYS`.
  > ⚠️ **Kalitni yo'qotsangiz, barcha yuz andozalari va kamera manzillari ochilmaydi.** Uni bazadan alohida, xavfsiz joyda saqlang. Almashtirish: yangi kalitni birinchi o'ringa, eskisini vergul bilan qoldiring.
- Loglarda faqat ID lar; RTSP manzil va parollar chiqmaydi.
- Kamera faqat yopiq lokal tarmoqda bo'lishi kerak.
- **Rozilik:** buyurtmachi qarori (20.11.2026) bilan tizimda talab qilinmaydi. Bu TZ 5-bo'limidan chetlanish — ota-ona roziligini qog'ozda tashkiliy tarzda olish tavsiya etiladi; huquqiy jihat buyurtmachi zimmasida.
- Zaxira nusxalarda o'chirilgan andozalar saqlanish muddati tugaguncha qoladi — muddatni (masalan, 30 kun) belgilang.

---

## 10. Dasturchi uchun

### Kod xaritasi

| Fayl/papka | Vazifasi |
|---|---|
| [app/core/models.py](app/core/models.py) | Barcha modellar: User (rol), Room, Camera, SchoolClass, Student, TeacherAssignment, FaceTemplate, RecognitionSettings, Session, AttendanceRecord, VisibilityInterval, CameraEvent, AuditLog, CameraCheck, ObserverAnnotation |
| [app/core/services.py](app/core/services.py) | **Biznes-mantiq markazi:** sessiya hayot sikli, belgilash, tasdiqlash, andoza yaratish/o'chirish, hisobot, pilot metrikalari. View'lar faqat shu yerni chaqiradi |
| [app/core/views/](app/core/views/) | `sessions.py` (o'qituvchi oqimi + JSON API), `manage.py` (o'quvchilar, rasmlar, audit, pilot), `crud.py` (umumiy CRUD), `cameras.py` (jonli kadr proksisi) |
| [app/vision/worker.py](app/vision/worker.py) | `Supervisor` (har 1 s bazani kuzatadi) va `SessionRunner` (bitta sessiya tahlili) |
| [app/vision/matcher.py](app/vision/matcher.py) | Moslik qoidasi — sof mantiq, to'liq testlangan |
| [app/vision/engine.py](app/vision/engine.py) | YuNet/SFace o'rami, sifat o'lchovlari |
| [app/vision/capture.py](app/vision/capture.py) | Kadr olish, qayta ulanish |
| [app/vision/hub.py](app/vision/hub.py), [preview.py](app/vision/preview.py) | Kamera markazi va jonli ko'rish HTTP serveri |
| [app/core/crypto.py](app/core/crypto.py) | Shifrlash |
| [app/templates/](app/templates/), [app/static/](app/static/) | Interfeys (o'zbek, lotin) |
| [run_local.py](run_local.py) | Lokal launcher |
| [docker-compose.yml](docker-compose.yml), [app/Dockerfile](app/Dockerfile), [deploy/Caddyfile](deploy/Caddyfile) | Server joylashtirish |

### Asosiy buyruqlar (PowerShell, `D:\Projects\unib\app` ichida)

```powershell
..\.venv\Scripts\python.exe manage.py test            # 40 ta test
..\.venv\Scripts\python.exe manage.py runserver       # veb (1-terminal)
..\.venv\Scripts\python.exe manage.py run_worker      # worker (2-terminal)
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py ensure_admin    # INITIAL_ADMIN_* dan admin yaratadi
..\.venv\Scripts\python.exe manage.py seed_demo --students 5 [--rtsp rtsp://...]
```

Bazani noldan boshlash: ikkala jarayonni to'xtating → `del app\dev.sqlite3*` → `ishga_tushirish.bat`. **`app\.env` ni o'chirmang** (kalit unda).

### Serverga chiqarish (Docker) — hali sinalmagan

```bash
cp .env.example .env
# to'ldiring: DJANGO_SECRET_KEY, DB_PASSWORD, INITIAL_ADMIN_PASSWORD, FIELD_ENCRYPTION_KEYS,
#             SITE_ADDRESS, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS
docker compose up -d --build
# brauzer: https://<SITE_ADDRESS>
```

Konteynerlar: `db` (PostgreSQL), `web` (Gunicorn), `worker`, `proxy` (Caddy, LAN uchun ichki sertifikat). Kamerasiz sinov: `docker compose --profile demo up -d rtsp` + ffmpeg bilan video uzatish (README'da).

### Ishlash qoidalari

- Yangi mantiqni **`services.py`** ga yozing, view'da emas; har bir qo'lda o'zgarish `services.audit(...)` orqali auditga tushsin.
- Ruxsat **server tomonda** tekshiriladi (`can_view_session`, `can_edit_marks`, `admin_required`).
- Kadr yoki yuz kesimini diskka/bazaga ochiq yozmang — bu TZ ning asosiy talabi.
- Loglarga ism, RTSP manzil yozmang — faqat ID.
- Model o'zgarsa — migratsiya (`makemigrations`), keyin testlar.

### Mavjud hujjatlar

| Fayl | Mazmuni |
|---|---|
| [README.md](README.md) | Arxitektura, Docker, talablar jadvali |
| [LOYIHA_HOLATI.md](LOYIHA_HOLATI.md) | Batafsil holat, tekshiruv natijalari, o'zgarishlar tarixi |
| [LOKAL_ISHGA_TUSHIRISH.md](LOKAL_ISHGA_TUSHIRISH.md) | Docker'siz ishga tushirish, muammolar |
| `Texnik topshiriq ... (MVP).pdf` | Asl TZ (12 bet) |

---

## 11. Muammolar va yechimlar

| Muammo | Yechim |
|---|---|
| Sessiya «Ulanmoqda»/«Uzilgan» dan chiqmayapti | Kamera boshqa dasturda band (Zoom, Teams, Kamera ilovasi, rasm olayotgan brauzer oynasi). Yoping — worker 2–30 s da o'zi ulanadi |
| «Tahlil jarayoni javob bermayapti» | Worker ishlamayapti. `ishga_tushirish.bat` ni qayta ishga tushiring |
| «Bu xonaga faol kamera biriktirilmagan» | Kameralar nazorati → kamera qo'shing yoki «faol» qiling |
| O'qituvchi sessiya ocha olmayapti / sinf ro'yxatda yo'q | Biriktiruvlar → o'qituvchi + sinf + xona qo'shing |
| «Bu kamerada boshqa faol sessiya bor» | Avvalgi sessiyani yakunlang (Faol sessiyalar) |
| Kompyuterda bir nechta kamera | Kamera sozlamasida manzilni `1` yoki `2` qiling |
| Meni tanimayapti / «Noaniq» | Qo'shimcha rasm qo'shing; kerak bo'lsa `T` ni 0,33 ga tushiring |
| `database is locked` | Faqat bitta `runserver` va bitta `run_worker` ishlayotganini tekshiring |
| 8000-port band | `set PORT=8001` keyin `ishga_tushirish.bat` |
| Kod yangilandi, lekin o'zgarish ko'rinmayapti | `Ctrl+C` → qayta ishga tushiring (launcher avtomatik qayta yuklamaydi) |

---

## 12. Tahlilda topilgan kamchiliklar

Kodni to'liq ko'rib chiqishda topilgan, hali tuzatilmagan narsalar. Ular tizim ishlashiga to'sqinlik qilmaydi, lekin serverga chiqishdan oldin hal qilish kerak.

| # | Kamchilik | Ta'siri | Taklif |
|---|---|---|---|
| 1 | [app/templates/base.html](app/templates/base.html) va kirish sahifasi Google Fonts'dan shrift yuklaydi, hujjatlarda esa «tashqi CDN'siz» deyilgan | Internetsiz LAN'da shrift almashadi (sekin ochilish mumkin); har bir sahifa ochilganda tashqi serverga so'rov ketadi | Inter/JetBrains Mono fayllarini `static/fonts/` ga qo'yish |
| 2 | Standart parollar (`Admin12345!`, `oqituvchi123`) launcher, `.env` va hujjatlarda ochiq yozilgan | Tarmoqqa ochilsa — xavf | Birinchi kirishda parolni almashtirish; serverda `seed_demo` ishlatmaslik |
| 3 | `app/dev.sqlite3-shm` va `app/dev.sqlite3-wal` git'ga qo'shilgan (`.gitignore` dagi `*.sqlite3` ularni qamramaydi) | Har ishga tushirishda git «o'zgargan» deb ko'rsatadi | `.gitignore` ga `*.sqlite3-*` qo'shish va `git rm --cached` |
| 4 | Lokal `.venv` — Python **3.14**, Docker obrazi — Python **3.12** | Lokalda o'tgan testlar serverda boshqacha bo'lishi mumkin | Docker build'da ham testlarni ishga tushirish |
| 5 | Docker Compose va PostgreSQL bilan umuman sinalmagan; testlar faqat SQLite'da | Serverda kutilmagan xatolar (masalan, `select_for_update`, qisman unikal indeks) | 13-bo'lim, 1-qadam |
| 6 | [LOKAL_ISHGA_TUSHIRISH.md](LOKAL_ISHGA_TUSHIRISH.md) da «Ran 28 tests» deyilgan (aslida 40) va namunada «10 ta o'quvchi» deyilgan (launcher 5 ta yaratadi) | Yangi odamni chalg'itadi | Hujjatni yangilash |
| 7 | CI (avtomatik test) yo'q, git tarixida bitta commit | O'zgarishlarni kuzatish qiyin | GitHub Actions/GitLab CI'da `manage.py test` |
| 8 | Liveness yo'q | Telefondagi rasm bilan «Keldi» qilish mumkin | Hozircha o'qituvchi tasdig'i; 2-bosqichda ko'rib chiqish |

---

## 13. Keyingi qadamlar (yo'l xaritasi)

| # | Vazifa | Kim | Natija |
|---|---|---|---|
| 1 | Lokal sinov: o'zingizni va 3–5 kishini tanittirish, chegaralarni his qilish | Jamoa | Tizim oqimi tushunilgan |
| 2 | 12-bo'limdagi 1–3, 6-kamchiliklarni tuzatish | Dasturchi | Serverga tayyor kod |
| 3 | `docker compose up -d --build` — PostgreSQL + HTTPS bilan to'liq sinov, testlarni PostgreSQL'da ishga tushirish | Dasturchi | Docker varianti tasdiqlangan |
| 4 | Server tanlash (O'zbekiston hududida), apparat tavsifi; zaxira nusxa va saqlash muddati siyosati | Buyurtmachi + dasturchi | Server tayyor |
| 5 | 1080p+ RTSP kamera, joylashuvi; «Kameralar nazorati» orqali barcha qatorlarni tekshirish | Administrator | Kamera o'rnatilgan |
| 6 | Ota-ona rozilik shakli (huquqshunos bilan) | Buyurtmachi | Huquqiy asos |
| 7 | **Pilot: kamida 2 hafta**, «mustaqil yo'qlama» rejimida | O'qituvchilar | FP/FN/kechikish ma'lumoti |
| 8 | Pilot natijasiga ko'ra `T`, `Δ`, `N` ni kalibrlash | Administrator + dasturchi | Yakuniy parametrlar |
| 9 | 2-bosqich bo'yicha qaror (ko'rinish qamrovi F-14 va kuzatuvchi ma'lumotlari F-17 asosida) | Buyurtmachi | Keyingi bosqich rejasi |

**Buyurtmachi bilan kelishilishi kerak bo'lgan ochiq savollar:** jonli kamera ko'rish (administrator va o'qituvchi sinfni jonli ko'radi), tasdiqdan keyin kim o'zgartira oladi, sessiya maksimal davomiyligi, kechikish holati va dars jadvali (MVP dan tashqari).

---

## 14. Atamalar lug'ati

| Atama | Ma'nosi |
|---|---|
| **Andoza** (template) | Yuz rasmidan olingan 128 ta sondan iborat shifrlangan «yuz izi». Rasmning o'zi saqlanmaydi |
| **Sessiya** | Bitta dars davomida bitta sinfning davomat yig'ilishi |
| **Worker** | Kameradan kadr olib, yuzlarni taniydigan alohida jarayon |
| **RTSP** | IP-kameralar video uzatish protokoli (`rtsp://...`) |
| **T, Δ, N** | O'xshashlik chegarasi, ikki nomzod farqi, tasdiqlovchi kadrlar soni |
| **Noaniq** | Kamera o'xshash nomzod topgan, lekin ishonch yetarli emas |
| **Mustaqil yo'qlama** (pilot blind) | O'qituvchi kamera natijasini ko'rmasdan oldin qo'lda yo'qlama qiladi — kamera aniqligini o'lchash uchun |
| **FP / FN / TP** | Kamera xato «Keldi» degan / kelganni topmagan / to'g'ri topgan |
| **Ko'rinish oralig'i** | O'quvchi kamerada ko'ringan vaqt bo'laklari (2-bosqich uchun) |
| **Audit jurnali** | Barcha qo'lda o'zgarishlar tarixi: kim, qachon, eski → yangi qiymat |
| **Fernet kaliti** | `FIELD_ENCRYPTION_KEYS` — andoza va kamera manzillarini shifrlash kaliti |
