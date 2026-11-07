#!/usr/bin/env python3
"""心情模块的测试。用合成音，不碰麦克风。

    python3 tests/test_mood.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import mood  # noqa: E402

SR = 16000


def tone(freq=200.0, seconds=1.0, amp=8000.0) -> bytes:
    t = np.arange(int(SR * seconds)) / SR
    sig = (np.sin(2 * np.pi * freq * t) * amp).astype(np.int16)
    return sig.tobytes()


def test_已知音高能算准():
    f = mood.analyze(tone(200.0))
    assert 185 < f["pitch"] < 215, f["pitch"]


def test_音高越高读数越高():
    low = mood.analyze(tone(150.0))["pitch"]
    high = mood.analyze(tone(300.0))["pitch"]
    assert high > low, (low, high)


def test_声音越小_db_越低():
    loud = mood.analyze(tone(200.0, amp=12000.0))["db"]
    quiet = mood.analyze(tone(200.0, amp=1500.0))["db"]
    assert loud > quiet, (loud, quiet)


def test_样本不足时不瞎猜():
    m = mood.Mood()
    r = m.read(tone())
    assert r["mood"] == "平稳"
    assert "样本太少" in r["hint"]


def test_比平时大声会被认出来():
    m = mood.Mood()
    for _ in range(4):
        m.read(tone(amp=4000.0))
    r = m.read(tone(amp=12000.0))
    assert r["mood"] == "有精神", r
    assert r["rate"] > 180, "有精神的时候应该说得快一点"


def test_比平时小声会被认出来():
    m = mood.Mood()
    for _ in range(4):
        m.read(tone(amp=12000.0))
    r = m.read(tone(amp=2500.0))
    assert r["mood"] in ("疲惫", "低落"), r
    assert r["rate"] < 170, "低落的时候应该说得慢一点"


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
