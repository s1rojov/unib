# Lokal ishga tushirish (Docker'siz, kompyuter kamerasi bilan)

## ⚡ Bitta buyruq bilan

`D:\Projects\unib\ishga_tushirish.bat` faylini **ikki marta bosing** yoki PowerShell'da:

```powershell
cd D:\Projects\unib
.\ishga_tushirish.bat
```

Bu buyruq kerak bo'lsa hammasini o'zi bajaradi:
1. Python muhitini (`.venv`) yaratadi va kutubxonalarni o'rnatadi.
2. Yuzni tanish modellarini yuklab oladi.
3. Tasodifiy kalitlar bilan `app\.env` faylini yaratadi.
4. Bazani tayyorlaydi; birinchi marta administrator, o'qituvchi va namunaviy sinfni yaratadi.
5. Veb-server va kamera tahlilini birga ishga tushirib, brauzerda **http://127.0.0.1:8000** ni ochadi.

To'xtatish: konsolda `Ctrl+C` — ikkala jarayon ham to'xtaydi.
Kirish: `admin` / `Admin12345!` yoki `oqituvchi` / `oqituvchi123`. Keyingi qadamlar quyidagi **4-bo'limda**.

Boshqa port kerak bo'lsa: `set PORT=8001` buyrug'idan keyin `.\ishga_tushirish.bat`.

Quyidagi 1–3-bo'limlar launcher'siz, qo'lda ishga tushirish uchun.

Barcha buyruqlar **PowerShell** uchun. Loyiha papkasi: `D:\Projects\unib`.
Tizim ikki jarayondan iborat: **veb-server** (Django) va **worker** (kameradan yuzlarni tanish). Ular ikkita alohida terminalda ishlaydi va bitta SQLite bazasi (`app\dev.sqlite3`) orqali aloqa qiladi.

---

## 1. Bir martalik tayyorgarlik

> Hozirgi kompyuterda 1.1–1.3-qadamlar **allaqachon bajarilgan** (`.venv`, modellar va `app\.env` mavjud). Darhol 2-qadamdan boshlang.

### 1.1. Python muhiti va kutubxonalar

```powershell
cd D:\Projects\unib
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
```

### 1.2. Yuzni tanish modellari (OpenCV Zoo)

```powershell
mkdir app\models -Force
curl.exe -L -o app\models\face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
curl.exe -L -o app\models\face_recognition_sface_2021dec.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
```

### 1.3. Sozlamalar fayli `app\.env`

```powershell
cd D:\Projects\unib\app
copy .env.example .env
# Kalitlarni yarating va .env ichidagi DJANGO_SECRET_KEY va FIELD_ENCRYPTION_KEYS ga qo'ying:
..\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
..\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> ⚠️ `FIELD_ENCRYPTION_KEYS` — yuz andozalarini shifrlash kaliti. Uni o'zgartirsangiz yoki yo'qotsangiz, saqlangan andozalarni ochib bo'lmaydi.

---

## 2. Bazani tayyorlash (birinchi marta)

```powershell
cd D:\Projects\unib\app
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py ensure_admin
..\.venv\Scripts\python.exe manage.py seed_demo --students 5
```

Natijada quyidagilar yaratiladi:

| Nima | Qiymat |
|---|---|
| Administrator | login `admin`, parol `Admin12345!` (`app\.env` dagi `INITIAL_ADMIN_PASSWORD`) |
| O'qituvchi | login `oqituvchi`, parol `oqituvchi123` |
| Xona / kamera | `101-xona`, «Sinf kamerasi» = **kompyuter kamerasi `0`** |
| Sinf | `7-A (2026-2027)`, 5 ta o'quvchi: «Oʻquvchi 01» … «Oʻquvchi 05» |

---

## 3. Ishga tushirish (har safar)

**1-terminal — veb-server:**

```powershell
cd D:\Projects\unib\app
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

**2-terminal — worker (kamera tahlili):**

```powershell
cd D:\Projects\unib\app
..\.venv\Scripts\python.exe manage.py run_worker
```

Brauzerda oching: **http://127.0.0.1:8000** (Chrome yoki Edge).
To'xtatish: har bir terminalda `Ctrl+C`.

> Worker kamerani faqat kerak bo'lganda yoqadi: sessiya ochiq bo'lganda yoki «Kameralar nazorati»da jonli ko'rish yoqilganda. Keyin kamera bo'shatiladi.

> ⚠️ Kod yangilangandan keyin dasturni **qayta ishga tushiring**: oynada `Ctrl+C`, so'ng yana `ishga_tushirish.bat`.

---

## 4. Birinchi sinov: o'zingizni tanittirish

1. **`admin` bilan kiring** → yon menyuda «Oʻquvchilar bazasi»:
   **Sinflar** (sinf qo'shish) → **Oʻquvchilar** (familiya, ism, sinf) → **Yuz rasmlari**.
   Namunaviy ma'lumotda 7-A sinf va 10 ta o'quvchi bor; «Oʻquvchi 01» ni «Tahrirlash» orqali o'z ismingizga o'zgartiring.
2. **«Yuz rasmlari»** → chap ro'yxatdan o'quvchini tanlang.
3. **«Kameradan suratga olish»** → «Kamerani yoqish» (brauzer ruxsat so'raydi) →
   kameraga qarab **3–5 ta surat** oling (to'g'riga, biroz chapga, biroz o'ngga) → «Biriktirish».
   Yoki «Fayldan yuklash» orqali tayyor rasmlarni tanlang. Har bir rasm bo'yicha natija chiqadi;
   holat **«tayyor»** bo'lishi kerak (kamida 3 ta rasm).
4. Chiqing va **`oqituvchi` bilan kiring** → «Sessiyani boshlash».
5. Kameraga qarab turing: 1–3 soniyada «Kamera aniqladi» soni 1 ga oshadi va siz **«Keldi — Kamera»** bo'lib chiqasiz.
   Qolgan o'quvchilar «Tekshirish kerak» holatida qoladi — ularni «Keldi»/«Kelmadi» tugmalari bilan belgilang.
6. «Sessiyani yakunlash» → «Davomatni tasdiqlash» → **hisobot** va «CSV yuklab olish».

Qo'shimcha imkoniyatlar:

- **Pilot rejimi:** sessiya boshlashda «Pilot: avval mustaqil yoʻqlama» belgilansa, o'qituvchi avval kamera natijasini ko'rmasdan qo'lda yo'qlama qiladi. Shundan FP/FN/TP hisoblanadi («Pilot metrikalari» sahifasi, admin).
- **Kameralar nazorati** (admin → «Kameralar nazorati»): har bir kameraning holati, faol sessiyasi va **jonli tasviri**.
  «▶ Jonli koʻrish» bosilsa kameradan tasvir chiqadi va har bir yuz rangli ramka bilan belgilanadi:
  - **yashil** — tanildi;
  - **sariq** — noaniq;
  - **qizil** — notanish;
  - **kulrang** — yuz kichik yoki sifat past.

  Sessiya ochiq bo'lsa, ramkada o'quvchi ismi va ball ko'rinadi. Sessiya bo'lmasa, faqat yuz o'lchami va sifati ko'rsatiladi (o'rnatish tekshiruvi).
  «Tekshiruvni saqlash» joriy kadr statistikasini tarixga yozadi. Tasvir yozib olinmaydi; kim ko'rgani audit jurnaliga tushadi.
- **Boshqaruv** (admin → «Boshqaruv»):
  - xonalar, kameralar, sinflar, o'quvchilar (CSV import bilan);
  - foydalanuvchilar va o'qituvchi biriktiruvlari;
  - tanish parametrlari (T, Δ, N, yuz sifati);
  - pilot metrikalari va audit jurnali.

---

## 5. Muammolar va yechimlar

| Muammo | Yechim |
|---|---|
| Sessiya «Uzilgan» / «Ulanmoqda» holatidan chiqmayapti | Kamera boshqa dasturda band (Zoom, Teams, Kamera ilovasi, andoza olinayotgan brauzer oynasi). Ularni yoping — worker 2–30 s ichida o'zi qayta ulanadi. |
| «Tahlil jarayoni javob bermayapti» | 2-terminalda `run_worker` ishlamayapti — uni ishga tushiring. |
| Kompyuterda bir nechta kamera bor | admin → «Kameralar nazorati» → «Sozlash» → manzil maydoniga `1` (yoki `2`) yozing. |
| Jonli ko'rishda «worker ishlamayapti» | Dasturni qayta ishga tushiring (`ishga_tushirish.bat`). Eski nusxa ochiq qolgan bo'lsa, avval uni `Ctrl+C` bilan yoping. |
| Brauzerda andoza uchun kamera ochilmayapti | Shu kamerada jonli ko'rish yoki sessiya ochiq — ularni to'xtating (kamera bir vaqtda bitta dasturda ishlaydi). |
| Andoza: «bosh burilgan», «xira», «yuz kichik» | Yorug' joyda, kameraga yaqinroq turib, to'g'riroq qarab qayta suratga oling. |
| Meni tanimayapti yoki «Noaniq» chiqyapti | Yana 1–2 ta andoza qo'shing (boshqa burchak va yorug'likda). Kerak bo'lsa «Tanish parametrlari»da T ni biroz pasaytiring (masalan, 0,33). |
| `database is locked` | Bitta `runserver` va bitta `run_worker` ishlayotganini tekshiring (ortiqcha nusxalarni yoping). |
| 8000-port band | `runserver 127.0.0.1:8001` va brauzerda shu portni oching. |
| Hammasini noldan boshlash | Ikkala jarayonni to'xtating → `del app\dev.sqlite3*` → 2-qadamni qaytadan bajaring. `app\.env` ni o'chirmang. |

---

## 6. Testlar

```powershell
cd D:\Projects\unib\app
..\.venv\Scripts\python.exe manage.py test
```

Kutilgan natija: `Ran 28 tests ... OK`. Ruxsatlarni tekshiruvchi testlar logga `Forbidden` yozadi — bu normal.
