#!/usr/bin/env python3
"""眨眼的测试：间隔在范围里、会连眨、状态不漂。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from face import BLINK_CLOSED, BLINK_MAX, BLINK_MIN, STATES, Blinker, Face  # noqa: E402


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
    f = Face("idle")
    img = f.render(120, now=0.0, t=0.5, blink=1.0)
    assert img.shape == (120, 120, 3)


def test_渲染不是全黑():
    import numpy as np

    f = Face("idle")
    img = f.render(160, now=0.0, t=0.5, blink=1.0)
    assert float(np.mean(img)) > 5, "立绘没加载上"


def test_闭眼和睁眼不一样():
    import numpy as np

    f = Face("idle")
    a = f.render(128, now=0.0, t=0.0, blink=1.0)
    b = f.render(128, now=0.0, t=0.0, blink=0.0)
    assert float(np.abs(a.astype(int) - b.astype(int)).mean()) > 0.5


def test_每种情绪都能渲染():
    f = Face("idle")
    for name in STATES:
        img = f.render(96, now=0.0, t=0.4, blink=1.0)
        assert img is not None and img.size > 0, name


def test_换情绪会记下来():
    f = Face("idle")
    f.set("happy", now=0.0)
    assert f.name == "happy"


def test_同一个情绪不会重新触发():
    f = Face("idle")
    f.set("happy", now=0.0)
    f.render(64, now=0.3, t=0.0, blink=1.0)
    f.set("happy", now=0.4)
    assert f.name == "happy"


def test_说话时嘴会动():
    import numpy as np

    f = Face("talking")
    a = f.render(128, now=0.0, t=0.10, blink=1.0)
    b = f.render(128, now=0.0, t=0.35, blink=1.0)
    assert float(np.abs(a.astype(int) - b.astype(int)).mean()) > 0.2


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
