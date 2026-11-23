"""Moslikni tasdiqlash qoidasi (TZ 4-bo'lim). OpenCV ga bog'liq emas — testlanadi.

1. Yuz sifati: minimal o'lcham, tiniqlik, bosh burilishi chegaradan o'tadi.
2. Kosinus o'xshashlik >= T.
3. Eng yaqin ikki nomzod (turli o'quvchilar) farqi >= Δ.
4. Bir o'quvchi uchun vaqt oynasida kamida N ta kadrda tasdiq.
5. Biror shart bajarilmasa — noaniq moslik, davomat soniga qo'shilmaydi.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

RELIABLE = "reliable"
UNCERTAIN = "uncertain"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class MatchParams:
    sim_threshold: float = 0.363
    margin_delta: float = 0.05
    uncertain_threshold: float = 0.30
    confirm_frames: int = 3
    confirm_window_seconds: float = 10.0
    min_face_px: int = 40
    min_blur_var: float = 25.0
    max_yaw_deg: float = 40.0
    visibility_gap_seconds: float = 10.0

    @classmethod
    def from_settings(cls, s) -> "MatchParams":
        return cls(
            sim_threshold=s.sim_threshold,
            margin_delta=s.margin_delta,
            uncertain_threshold=s.uncertain_threshold,
            confirm_frames=max(1, s.confirm_frames),
            confirm_window_seconds=float(s.confirm_window_seconds),
            min_face_px=s.min_face_px,
            min_blur_var=s.min_blur_var,
            max_yaw_deg=s.max_yaw_deg,
            visibility_gap_seconds=float(s.visibility_gap_seconds),
        )


@dataclass(frozen=True)
class FaceQuality:
    size_px: float
    blur_var: float
    yaw_deg: float
    det_score: float = 1.0

    def passes(self, min_px: float, min_blur: float, max_yaw: float) -> bool:
        return self.size_px >= min_px and self.blur_var >= min_blur and self.yaw_deg <= max_yaw

    def reasons(self, min_px: float, min_blur: float, max_yaw: float) -> list[str]:
        out = []
        if self.size_px < min_px:
            out.append(f"yuz kichik ({self.size_px:.0f}px < {min_px:.0f}px)")
        if self.blur_var < min_blur:
            out.append(f"xira ({self.blur_var:.0f} < {min_blur:.0f})")
        if self.yaw_deg > max_yaw:
            out.append(f"bosh burilgan ({self.yaw_deg:.0f}° > {max_yaw:.0f}°)")
        return out


def estimate_yaw_deg(landmarks: np.ndarray) -> float:
    """5 ta tayanch nuqtadan bosh burilishini taxminan baholaydi (graduslarda, mutlaq qiymat).

    landmarks: [[o'ng_ko'z], [chap_ko'z], [burun], [og'iz_o'ng], [og'iz_chap]] (x, y).
    Burun uchining ko'zlar o'rtasidan ko'zlar o'qi bo'ylab siljishi ko'zlar orasidagi
    masofaga nisbatan olinadi; burun chuqurligi ~0.5 * ko'zlar oralig'i deb qabul qilinadi.
    """
    lm = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    right_eye, left_eye, nose = lm[0], lm[1], lm[2]
    axis = left_eye - right_eye
    dist = float(np.hypot(*axis))
    if dist < 1e-6:
        return 90.0
    axis /= dist
    offset = float(np.dot(nose - (right_eye + left_eye) / 2.0, axis))
    return float(np.degrees(np.arctan(abs(offset) / dist / 0.5)))


class Gallery:
    """Sinf andozalari: har bir o'quvchi uchun bir nechta normallashgan vektor."""

    def __init__(self, student_ids: list[int], vectors: np.ndarray):
        self.vectors = _normalize(np.asarray(vectors, dtype=np.float32).reshape(len(student_ids), -1)) \
            if len(student_ids) else np.zeros((0, 128), np.float32)
        ids = np.asarray(student_ids, dtype=np.int64)
        self.students, self._index = np.unique(ids, return_inverse=True) if len(ids) else (
            np.zeros(0, np.int64), np.zeros(0, np.int64))

    def __len__(self):
        return int(self.students.shape[0])

    def best_two(self, feature: np.ndarray) -> tuple[int | None, float, int | None, float]:
        """Eng yaqin ikki *turli* o'quvchi va ularning ballari (har o'quvchi uchun maksimal)."""
        if len(self) == 0:
            return None, -1.0, None, -1.0
        f = _normalize(np.asarray(feature, dtype=np.float32).reshape(1, -1))[0]
        sims = self.vectors @ f
        per_student = np.full(len(self), -1.0, dtype=np.float32)
        np.maximum.at(per_student, self._index, sims)
        if len(self) == 1:
            return int(self.students[0]), float(per_student[0]), None, -1.0
        top2 = np.argpartition(-per_student, 1)[:2]
        top2 = top2[np.argsort(-per_student[top2])]
        i1, i2 = int(top2[0]), int(top2[1])
        return int(self.students[i1]), float(per_student[i1]), int(self.students[i2]), float(per_student[i2])


def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n < 1e-12] = 1.0
    return m / n


@dataclass
class Candidate:
    """Kadrdagi bitta yuz uchun natija."""

    quality_ok: bool
    sid1: int | None
    s1: float
    sid2: int | None
    s2: float


@dataclass
class Decision:
    kind: str  # RELIABLE / UNCERTAIN / UNKNOWN
    student_id: int | None
    score: float


def classify(c: Candidate, p: MatchParams) -> Decision:
    if c.sid1 is None:
        return Decision(UNKNOWN, None, c.s1)
    margin_ok = c.sid2 is None or (c.s1 - c.s2) >= p.margin_delta
    if c.quality_ok and c.s1 >= p.sim_threshold and margin_ok:
        return Decision(RELIABLE, c.sid1, c.s1)
    if c.s1 >= p.uncertain_threshold:
        return Decision(UNCERTAIN, c.sid1, c.s1)
    return Decision(UNKNOWN, None, c.s1)


def decide_frame(candidates: list[Candidate], p: MatchParams) -> list[Decision]:
    """Kadrdagi barcha yuzlar uchun qaror. Bitta o'quvchiga bir kadrda ikki yuz
    ishonchli moslansa, faqat eng yuqori balli qoladi, qolganlari noaniq bo'ladi."""
    decisions = [classify(c, p) for c in candidates]
    best: dict[int, int] = {}
    for i, d in enumerate(decisions):
        if d.kind != RELIABLE:
            continue
        j = best.get(d.student_id)
        if j is None or d.score > decisions[j].score:
            if j is not None:
                decisions[j] = Decision(UNCERTAIN, decisions[j].student_id, decisions[j].score)
            best[d.student_id] = i
        else:
            decisions[i] = Decision(UNCERTAIN, d.student_id, d.score)
    return decisions


class ConfirmationTracker:
    """4-shart: vaqt oynasida kamida N ta ishonchli kadr."""

    def __init__(self, n: int, window_seconds: float):
        self.n = max(1, int(n))
        self.window = timedelta(seconds=window_seconds)
        self._hits: dict[int, deque[datetime]] = {}
        self.confirmed: set[int] = set()

    def add(self, student_id: int, t: datetime) -> bool:
        """Ishonchli kadrni qo'shadi; o'quvchi shu kadrda yangi tasdiqlansa True."""
        if student_id in self.confirmed:
            return False
        q = self._hits.setdefault(student_id, deque())
        q.append(t)
        while q and t - q[0] > self.window:
            q.popleft()
        if len(q) >= self.n:
            self.confirmed.add(student_id)
            self._hits.pop(student_id, None)
            return True
        return False


@dataclass
class OpenInterval:
    student_id: int
    started_at: datetime
    last_seen_at: datetime
    frames: int = 1
    db_id: int | None = None
    dirty: bool = True


@dataclass
class VisibilityTracker:
    """F-14: har bir o'quvchi uchun tanilgan vaqt oraliqlari."""

    gap_seconds: float
    open: dict[int, OpenInterval] = field(default_factory=dict)
    closed: list[OpenInterval] = field(default_factory=list)

    def observe(self, student_id: int, t: datetime):
        cur = self.open.get(student_id)
        if cur is not None and (t - cur.last_seen_at).total_seconds() <= self.gap_seconds:
            cur.last_seen_at = t
            cur.frames += 1
            cur.dirty = True
            return
        if cur is not None:
            self.closed.append(cur)
        self.open[student_id] = OpenInterval(student_id, t, t)

    def expire(self, now: datetime):
        """Uzoq ko'rinmagan o'quvchilar oralig'ini yopadi."""
        for sid, cur in list(self.open.items()):
            if (now - cur.last_seen_at).total_seconds() > self.gap_seconds:
                self.closed.append(self.open.pop(sid))

    def close_all(self):
        self.closed.extend(self.open.values())
        self.open.clear()

    def pending(self) -> list[OpenInterval]:
        """Bazaga yozilishi kerak bo'lgan oraliqlar (yopilganlar + o'zgargan ochiqlar)."""
        out = list(self.closed) + [i for i in self.open.values() if i.dirty]
        self.closed = []
        return out
