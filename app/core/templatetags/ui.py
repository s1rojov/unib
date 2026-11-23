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
