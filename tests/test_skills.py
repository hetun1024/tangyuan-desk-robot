#!/usr/bin/env python3
"""技能包的测试：按需加载、平时不占地方。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.skills import Library  # noqa: E402


def make(tmp: str) -> Library:
    d = os.path.join(tmp, "demo")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "守则.md"), "w", encoding="utf-8").write("第一条：先接住情绪。")
    open(os.path.join(d, "trigger.txt"), "w", encoding="utf-8").write("难过\n吵架\n")
    return Library(tmp)


def test_命中触发词才加载():
    with tempfile.TemporaryDirectory() as tmp:
        lib = make(tmp)
        assert lib.match("我今天很难过")
        assert lib.match("今天写了个函数") == []


def test_没命中时提示词干净():
    with tempfile.TemporaryDirectory() as tmp:
        lib = make(tmp)
        assert lib.prompt("写代码") == ""
        assert "先接住情绪" in lib.prompt("我们吵架了")


def test_仓库里的love技能能读到():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    lib = Library(root)
    assert "love" in lib.names()
    assert "不诊断" in lib.prompt("我跟他分手了")


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
