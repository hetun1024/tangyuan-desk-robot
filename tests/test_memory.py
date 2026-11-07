#!/usr/bin/env python3
"""长期记忆的测试：存、取、忘、以及"记忆有没有真的进到提示词里"。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import Brain  # noqa: E402
from agent.config import Config  # noqa: E402
from agent.loop import Agent  # noqa: E402
from agent.memory import Memory  # noqa: E402


def tmp_memory() -> Memory:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return Memory(path)


def test_存了还能读出来():
    m = tmp_memory()
    m.set("名字", "小满")
    assert m.get("名字") == "小满"
    assert "小满" in m.prompt()


def test_换一个实例还在():
    m = tmp_memory()
    m.set("城市", "上海")
    again = Memory(m.path)
    assert again.get("城市") == "上海"


def test_可以忘掉():
    m = tmp_memory()
    m.set("口味", "美式")
    m.drop("口味")
    assert "口味" not in m.facts


def test_空键值被拒绝():
    m = tmp_memory()
    assert "不能为空" in m.set("", "x")
    assert not m.facts


def test_没有记忆时提示先去认识():
    m = tmp_memory()
    assert "还不认识" in m.prompt()


def test_记忆会进到系统提示里():
    m = tmp_memory()
    m.set("名字", "小满")
    agent = Agent(Brain(Config()), Config(), memory=m)
    agent._refresh_system()
    assert "小满" in agent.history[0]["content"]


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
