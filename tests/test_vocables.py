#!/usr/bin/env python3
"""拟声词的测试：认得出、别太吵。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import vocables  # noqa: E402


def test_认得出被夸():
    assert vocables.detect("你好可爱啊") == "praise"


def test_认得出累():
    assert vocables.detect("我有点累了") == "tired"


def test_认得出叫人():
    assert vocables.detect("汤圆") == "called"
    assert vocables.detect("喂？") == "called"


def test_普通话不触发():
    assert vocables.detect("今天天气怎么样") is None


def test_普通事件会限流():
    v = vocables.Voice(min_gap=3, chance=1.0, seed=1)
    fired = sum(1 for _ in range(9) if v.maybe("thinking"))
    assert fired <= 4, "9 轮里最多出 4 次，实际 %d" % fired


def test_被夸不受限流():
    v = vocables.Voice(min_gap=99, chance=1.0, seed=1)
    assert v.maybe("praise")
    assert v.maybe("praise")


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
