#!/usr/bin/env python3
"""读空气的测试：几种典型状态能不能认出来。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import room  # noqa: E402


def mode(t, p=None):
    return room.read(t, p or [])["mode"]


def test_急了():
    assert mode("快点！现在就要！") == "act_fast"


def test_怀疑():
    assert mode("真的吗？你确定？") == "show_basis"


def test_谨慎():
    assert mode("可能不太稳，先别动") == "narrow_scope"


def test_满意():
    assert mode("好的谢谢，就这样") == "close_it"


def test_情绪低():
    assert mode("我最近压力好大") == "comfort"


def test_普通的话不乱判():
    assert mode("今天天气不错") == "normal"
    assert room.overlay_for("今天天气不错") == ""


def test_重复问同一句会加怀疑分():
    q = "这个怎么弄"
    assert room.read(q, [q])["scores"]["show_basis"] > room.read(q, ["别的话"])["scores"]["show_basis"]


def test_每种状态都有对应的应对话():
    for t, want in [("快点！", "act_fast"), ("真的吗", "show_basis"),
                    ("可能不行", "narrow_scope"), ("谢谢", "close_it"),
                    ("好累", "comfort")]:
        r = room.read(t)
        assert r["mode"] == want, (t, r["mode"])
        assert r["overlay"], "每个状态都得有一句应对方式"


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
