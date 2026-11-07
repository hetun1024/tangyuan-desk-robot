#!/usr/bin/env python3
"""眨眼的测试：间隔在范围里、会连眨、状态不漂。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from face import (BLINK_CLOSED, BLINK_MAX, BLINK_MIN, PRESETS, Blinker,  # noqa: E402
                  Face, blend, draw_face)


def intervals(b: Blinker):
    starts = [e[0] for e in b.events]
    return [b2 - a2 for a2, b2 in zip(starts, starts[1:])]


def test_单次间隔都在范围内_or_连眨():
    b = Blinker(seed=7)
    for i in range(0, 6000):
        b.at(i / 60.0)
    gaps = intervals(b)
    normal = [g for g in gaps if g > 0.5]
    assert normal, "一次都没眨"
    assert all(BLINK_MIN - 0.01 <= g <= BLINK_MAX + 0.01 for g in normal), (min(normal), max(normal))


def test_会出现连眨():
    b = Blinker(seed=3)
    for i in range(0, 12000):
        b.at(i / 60.0)
    gaps = intervals(b)
    assert any(g <= 0.5 for g in gaps), "一整段里没有连眨"


def test_闭眼期间返回闭眼值():
    b = Blinker(seed=5)
    for i in range(0, 3000):
        b.at(i / 60.0)
    start, end = b.events[3]
    mid = (start + end) / 2
    assert b.at(mid) < 0.5
    assert b.at(mid + 1.0) > 0.5


def test_时间跳很久也不会爆():
    b = Blinker(seed=11)
    b.at(0.0)
    assert b.at(100000.0) in (0.08, 1.0)
    assert len(b.events) < 500


def test_画面能画出来():
    img = draw_face(120, dict(PRESETS["star"]), 1.0, blink=0.08)
    assert img.shape == (120, 120, 3)


def test_数字参数会连续变化():
    a, b = PRESETS["idle"], PRESETS["sad"]
    mid = blend(a, b, 0.5)
    assert abs(mid["blush"] - (a["blush"] + b["blush"]) / 2) < 1e-6


def test_形状在中点切换():
    a, b = PRESETS["idle"], PRESETS["happy"]
    assert blend(a, b, 0.3)["shape"] == "round"
    assert blend(a, b, 0.7)["shape"] == "arc"


def test_形状切换时眼睛会缩一下():
    a, b = PRESETS["idle"], PRESETS["star"]
    assert blend(a, b, 0.5)["eye_scale"] < 0.6


def test_过渡走完会停住():
    f = Face("idle")
    f.set("happy", 0.0)
    assert f.current(0.0)["shape"] == "round"
    end = f.current(10.0)
    assert end["shape"] == "arc"
    assert f.dur == 0.0


def test_同一个表情不会重新开始过渡():
    f = Face("happy")
    f.set("happy", 5.0)
    assert f.dur == 0.0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("ok    %s" % fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL  %s: %s" % (fn.__name__, e))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("ERROR %s: %s: %s" % (fn.__name__, type(e).__name__, e))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
