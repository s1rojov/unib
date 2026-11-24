from django import template

register = template.Library()


@register.filter
def pct(value, digits=0):
    """0..1 qiymatni foizga aylantiradi."""
    if value is None or value == "":
        return "—"
    return f"{float(value) * 100:.{int(digits)}f}%"


@register.filter
def pct_width(value):
    if value is None:
        return 0
    return max(0, min(100, round(float(value) * 100)))


@register.filter
def seconds(value):
    if value is None:
        return "—"
    v = float(value)
    if v < 60:
        return f"{v:.1f} s"
    m, s = divmod(int(round(v)), 60)
    h, m = divmod(m, 60)
    return f"{h} soat {m} daq" if h else f"{m} daq {s} s"


@register.filter
def initials(name):
    """«Aliyev Vali» → «AV» (avatar uchun)."""
    parts = [p for p in str(name or "").replace("ʻ", "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@register.filter
def get_item(d, key):
    return d.get(key) if d else None


@register.simple_tag
def asset(path):
    """Statik fayl URL'i + o'zgarish vaqti (?v=...): fayl yangilansa brauzer keshi avtomatik yangilanadi."""
    import os

    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    if "?" in url:  # manifest storage allaqachon xesh qo'shgan
        return url
    found = finders.find(path)
    try:
        return f"{url}?v={int(os.path.getmtime(found))}" if found else url
    except OSError:
        return url


_UZ_DAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
_UZ_MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


@register.simple_tag
def today_uz():
    """«Seshanba, 24-noyabr 2026» — brauzer tilidan qat'i nazar o'zbekcha."""
    from django.utils import timezone

    d = timezone.localdate()
    return f"{_UZ_DAYS[d.weekday()]}, {d.day}-{_UZ_MONTHS[d.month - 1]} {d.year}"
