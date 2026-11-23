from datetime import datetime, timedelta, timezone as tz

import numpy as np
from django.test import SimpleTestCase

from vision.capture import backoff_delays
from vision.matcher import (
    RELIABLE,
    UNCERTAIN,
    UNKNOWN,
    Candidate,
    ConfirmationTracker,
    FaceQuality,
    Gallery,
    MatchParams,
    VisibilityTracker,
    classify,
    decide_frame,
    estimate_yaw_deg,
)

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=tz.utc)
P = MatchParams(sim_threshold=0.363, margin_delta=0.05, uncertain_threshold=0.30, confirm_frames=3,
                confirm_window_seconds=10, visibility_gap_seconds=10)


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


class GalleryTests(SimpleTestCase):
    def test_best_two_uses_per_student_max(self):
        rng = np.random.default_rng(0)
        a1, a2, b = unit(rng.normal(size=128)), unit(rng.normal(size=128)), unit(rng.normal(size=128))
        g = Gallery([1, 1, 2], np.stack([a1, a2, b]))
        self.assertEqual(len(g), 2)
        sid1, s1, sid2, s2 = g.best_two(a2)
        self.assertEqual(sid1, 1)
        self.assertAlmostEqual(s1, 1.0, places=5)
        self.assertEqual(sid2, 2)
        self.assertLess(s2, 0.5)

    def test_empty_and_single(self):
        self.assertEqual(Gallery([], np.zeros((0, 128))).best_two(unit(np.ones(128)))[0], None)
        g = Gallery([7], unit(np.ones(128))[None, :])
        sid1, s1, sid2, _ = g.best_two(unit(np.ones(128)))
        self.assertEqual((sid1, sid2), (7, None))


class ClassifyTests(SimpleTestCase):
    def test_reliable_requires_quality_threshold_and_margin(self):
        self.assertEqual(classify(Candidate(True, 1, 0.6, 2, 0.3), P).kind, RELIABLE)
        # sifat o'tmadi
        self.assertEqual(classify(Candidate(False, 1, 0.6, 2, 0.3), P).kind, UNCERTAIN)
        # farq Δ dan kichik (open-set / o'xshash ikki o'quvchi)
        self.assertEqual(classify(Candidate(True, 1, 0.50, 2, 0.47), P).kind, UNCERTAIN)
        # T dan past, lekin noaniq chegarasidan yuqori
        self.assertEqual(classify(Candidate(True, 1, 0.33, 2, 0.1), P).kind, UNCERTAIN)
        # begona yuz
        self.assertEqual(classify(Candidate(True, 1, 0.2, 2, 0.1), P).kind, UNKNOWN)

    def test_two_faces_same_student_in_one_frame(self):
        d = decide_frame([Candidate(True, 5, 0.55, 2, 0.1), Candidate(True, 5, 0.70, 2, 0.1)], P)
        self.assertEqual([x.kind for x in d], [UNCERTAIN, RELIABLE])


class TrackerTests(SimpleTestCase):
    def test_confirmation_needs_n_frames_within_window(self):
        t = ConfirmationTracker(3, 10)
        self.assertFalse(t.add(1, T0))
        self.assertFalse(t.add(1, T0 + timedelta(seconds=20)))  # birinchisi oynadan chiqdi
        self.assertFalse(t.add(1, T0 + timedelta(seconds=21)))
        self.assertTrue(t.add(1, T0 + timedelta(seconds=22)))
        # bir marta hisoblanadi
        self.assertFalse(t.add(1, T0 + timedelta(seconds=23)))
        self.assertIn(1, t.confirmed)

    def test_visibility_intervals(self):
        v = VisibilityTracker(gap_seconds=10)
        for s in (0, 2, 4):
            v.observe(1, T0 + timedelta(seconds=s))
        v.observe(1, T0 + timedelta(seconds=30))  # uzilish -> yangi oraliq
        pend = v.pending()
        self.assertEqual(len(pend), 2)
        first = [i for i in pend if i.started_at == T0][0]
        self.assertEqual(first.frames, 3)
        self.assertEqual(first.last_seen_at, T0 + timedelta(seconds=4))
        v.expire(T0 + timedelta(seconds=60))
        self.assertEqual(v.open, {})


class QualityTests(SimpleTestCase):
    def test_yaw_estimate(self):
        frontal = [[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]]
        turned = [[40, 50], [80, 50], [78, 70], [45, 90], [75, 90]]
        self.assertLess(estimate_yaw_deg(frontal), 1)
        self.assertGreater(estimate_yaw_deg(turned), 35)

    def test_quality_reasons(self):
        q = FaceQuality(size_px=30, blur_var=10, yaw_deg=50)
        self.assertFalse(q.passes(40, 25, 35))
        self.assertEqual(len(q.reasons(40, 25, 35)), 3)

    def test_backoff(self):
        g = backoff_delays(30)
        self.assertEqual([next(g) for _ in range(7)], [2, 4, 8, 16, 30, 30, 30])
