#!/usr/bin/env python3
"""说话的测试：括号里的动作不该念出来。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.voice import for_speech  # noqa: E402


def test_去掉中文括号动作():
    assert for_speech("（愣了一下）……你在念视频结尾词吧。") == "……你在念视频结尾词吧。"


def test_去掉半角括号动作():
    assert for_speech("(sigh) 好困。") == "好困。"


def test_句中的括号也要去掉():
    assert for_speech("嗯（顿了顿）……说吧。") == "嗯……说吧。"


def test_多个括号都去掉():
    t = for_speech("（叹气）河豚，（小声）你要是困了就去睡。")
    assert "（" not in t and "河豚" in t and "去睡" in t


def test_去掉markdown记号():
    assert for_speech("**重点**：这件事") == "重点：这件事"


def test_整句都是动作就返回空():
    assert for_speech("（只是动作，没有台词）") == ""


def test_正常的话不动():
    assert for_speech("前面有人，两米左右。") == "前面有人，两米左右。"


def test_不会误伤书名号():
    t = for_speech("我看过《活着》。")
    assert "《活着》" in t


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("ok    %s" % fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL  %s: %r" % (fn.__name__, e))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("ERROR %s: %s: %s" % (fn.__name__, type(e).__name__, e))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
